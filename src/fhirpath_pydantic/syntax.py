"""Immutable syntax trees using fhirpathpy's upstream ANTLR grammar."""

import re
from functools import lru_cache
from typing import Literal, override

from antlr4 import CommonTokenStream, InputStream, Lexer, Parser, ParserRuleContext, Token
from antlr4.error.ErrorListener import ErrorListener
from antlr4.tree.Tree import TerminalNode
from pydantic import BaseModel, ConfigDict

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

    def string_value(self) -> str:
        """Decode a FHIRPath literal without Python-specific escape semantics."""
        escapes = {"n": "\n", "r": "\r", "t": "\t", "f": "\f", "\\": "\\", "'": "'", '"': '"', "`": "`"}
        return re.sub(
            r"\\(u[0-9A-Fa-f]{4}|.)",
            lambda match: chr(int(match[1][1:], 16)) if match[1].startswith("u") else escapes.get(match[1], match[1]),
            self.text[1:-1],
        )

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
        result = cls.from_context(parser.expression())
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
