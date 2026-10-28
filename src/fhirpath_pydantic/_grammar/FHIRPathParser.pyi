from antlr4 import Parser, ParserRuleContext

class FHIRPathParser(Parser):
    def expression(self, _p: int = 0) -> ParserRuleContext: ...
