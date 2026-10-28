"""Immutable syntax trees using fhirpathpy's upstream ANTLR grammar."""

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


def _node(context: ParserRuleContext) -> Node:
    children: list[Node] = []
    tokens: list[str] = []
    for child in context.getChildren():
        if isinstance(child, TerminalNode):
            tokens.append(child.getText())
        else:
            children.append(_node(child))
    return Node(
        kind=type(context).__name__.removesuffix("Context"),
        text=context.getText(),
        tokens=tuple(tokens),
        children=tuple(children),
    )


@lru_cache(maxsize=512)
def parse(expression: str) -> Node:
    """Reject lexer/parser recovery and trailing tokens, caching syntax only."""
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
    result = _node(parser.expression())
    if stream.LA(1) != Token.EOF:
        raise FHIRPathError("Unexpected trailing input")
    return result
