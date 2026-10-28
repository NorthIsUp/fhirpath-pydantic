from antlr4 import Lexer, Parser, Token

class ErrorListener:
    def syntaxError(
        self,
        recognizer: Lexer | Parser,
        offendingSymbol: Token | None,
        line: int,
        column: int,
        msg: str,
        e: Exception | None,
    ) -> None: ...
