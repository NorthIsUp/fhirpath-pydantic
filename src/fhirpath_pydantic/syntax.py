"""Immutable syntax trees using fhirpathpy's upstream ANTLR grammar."""

import re
from functools import lru_cache
from typing import Literal, override

from antlr4 import CommonTokenStream, InputStream, Lexer, Parser, ParserRuleContext, Token
from antlr4.error.ErrorListener import ErrorListener
from antlr4.tree.Tree import TerminalNode
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from fhirpath_pydantic._grammar.FHIRPathLexer import FHIRPathLexer
from fhirpath_pydantic._grammar.FHIRPathParser import FHIRPathParser
from fhirpath_pydantic.types import FHIRPathError, Value


class Node(BaseModel):
    """A syntax node shared by parsed and programmatically built queries."""

    model_config = ConfigDict(frozen=True, strict=True)
    kind: str
    text: str = ""
    tokens: tuple[str, ...] = ()
    children: tuple[Node, ...] = ()
    value: Value = None
    source: Literal["grammar", "literal"] = "grammar"

    @classmethod
    def from_context(cls, context: ParserRuleContext) -> Node:
        """Build validated syntax directly from the generated grammar's tree."""
        children: list[Node] = []
        tokens: list[str] = []
        for child in context.getChildren():
            if isinstance(child, TerminalNode):
                tokens.append(child.getText())
            else:
                children.append(cls.from_context(child))
        return cls(
            kind=type(context).__name__.removesuffix("Context"),
            text=context.getText(),
            tokens=tuple(tokens),
            children=tuple(children),
        )

    @field_validator("tokens")
    @classmethod
    def validate_quoted_tokens(cls, tokens: tuple[str, ...]) -> tuple[str, ...]:
        """Reject invalid escapes in every quoted grammar token before evaluation."""
        for token in tokens:
            if token.startswith(("'", "`")):
                cls.decode_quoted(token)
        return tokens

    @staticmethod
    def escape_value(match: re.Match[str]) -> str:
        """Decode one escape without accepting a malformed Unicode sequence."""
        escape = match.group(1)
        assert isinstance(escape, str)
        if escape == "u":
            raise FHIRPathError("Invalid Unicode escape: expected four hexadecimal digits")
        if escape.startswith("u"):
            return chr(int(escape[1:], 16))
        escapes: dict[str, str] = {"n": "\n", "r": "\r", "t": "\t", "f": "\f", "\\": "\\", "'": "'", '"': '"', "`": "`"}
        return escapes.get(escape, escape)

    @classmethod
    def decode_quoted(cls, text: str) -> str:
        """Decode quoted text using FHIRPath's escape rules."""
        return re.sub(r"\\(u[0-9A-Fa-f]{4}|.)", cls.escape_value, text[1:-1])

    def string_value(self) -> str:
        """Decode a literal or quoted environment variable name."""
        return self.decode_quoted(self.text.removeprefix("%"))

    def name_value(self) -> str:
        """Decode names and qualified segments before runtime lookup."""
        match self.kind:
            case "TypeSpecifier" | "ExternalConstant" | "TermExpression" | "InvocationTerm" | "MemberInvocation" if (
                self.children
            ):
                return self.children[0].name_value()
            case "QualifiedIdentifier" | "InvocationExpression":
                return ".".join(child.name_value() for child in self.children)
            case _:
                text = self.text.removeprefix("%")
                return self.string_value() if text.startswith(("`", "'")) else text

    @classmethod
    @lru_cache(maxsize=512)
    def parse(cls, expression: str) -> Node:
        """Reject parser recovery and trailing tokens, caching syntax only."""
        if not expression.strip():
            raise FHIRPathError("FHIRPath expression cannot be empty")
        lexer = FHIRPathLexer(InputStream(expression))
        errors = _Errors()
        lexer.removeErrorListeners()
        lexer.addErrorListener(errors)
        stream = CommonTokenStream(lexer)
        parser = FHIRPathParser(stream)
        parser.removeErrorListeners()
        parser.addErrorListener(errors)
        try:
            result = cls.from_context(parser.expression())
        except ValidationError as error:
            raise FHIRPathError(str(error)) from error
        if stream.LA(1) != Token.EOF:
            raise FHIRPathError("Unexpected trailing input")
        return result


class _Errors(ErrorListener):
    @override
    def syntaxError(
        self,
        recognizer: Lexer | Parser,
        offendingSymbol: Token | None,
        line: int,
        column: int,
        msg: str,
        e: Exception | None,
    ) -> None:
        raise FHIRPathError(f"Invalid FHIRPath at {line}:{column}: {msg}")


def parse(expression: str) -> Node:
    """Parse text through the syntax model's validated constructor."""
    return Node.parse(expression)
