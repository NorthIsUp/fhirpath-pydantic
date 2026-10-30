"""Decimal comparison precision is shared by scalar and quantity values."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

from pydantic import ConfigDict, RootModel

from fhirpath_pydantic.types import FHIRPathError


class DecimalValue(RootModel[Decimal]):
    """A finite decimal whose comparison precision does not mutate its value."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    def arithmetic(self, operation: str, right: Decimal) -> Decimal:
        """Keep finite arithmetic exact and retain enough digits for division or remainders."""
        if not right.is_finite():
            raise FHIRPathError("Decimal operands must be finite")
        left_parts, right_parts = self.root.as_tuple(), right.as_tuple()
        left_exponent, right_exponent = left_parts.exponent, right_parts.exponent
        assert isinstance(left_exponent, int) and isinstance(right_exponent, int)
        match operation:
            case "+" | "-" | "mod":
                precision = max(self.root.adjusted(), right.adjusted()) - min(left_exponent, right_exponent) + 2
            case "*":
                precision = len(left_parts.digits) + len(right_parts.digits) + 2
            case "/":
                # Four times the divisor's coefficient length bounds its factors of two and five.
                precision = max(
                    len(left_parts.digits) + 4 * len(right_parts.digits) + 2,
                    self.root.adjusted() - right.adjusted() + len(right_parts.digits) + 2,
                )
            case _:
                raise FHIRPathError(f"Unsupported Decimal operation: {operation}")
        with localcontext() as context:
            context.prec = max(context.prec, precision)
            match operation:
                case "+":
                    return self.root + right
                case "-":
                    return self.root - right
                case "*":
                    return self.root * right
                case "/":
                    return self.root / right
                case _:
                    return self.root % right

    def scaled(self, numerator: Decimal, denominator: Decimal = Decimal(1)) -> Decimal:
        """Scale a magnitude using the same precision policy as scalar arithmetic."""
        product = self.arithmetic("*", numerator) if numerator != 1 else self.root
        return type(self).model_validate(product).arithmetic("/", denominator) if denominator != 1 else product

    def rounded(self, precision: int) -> Decimal:
        """Round fractional places without losing integer digits to the ambient context."""
        if precision < 0:
            raise FHIRPathError("round() precision cannot be negative")
        with localcontext() as context:
            context.prec = max(context.prec, self.root.adjusted() + precision + 2)
            return self.root.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)

    def quantum(self) -> Decimal:
        """Return the least meaningful fractional place, ignoring fractional zeroes."""
        parts = self.root.as_tuple()
        exponent = parts.exponent
        assert isinstance(exponent, int)
        digits = list(parts.digits)
        while exponent < 0 and digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        return Decimal(1).scaleb(min(0, exponent))

    def equivalent(self, right: Decimal, *, quantum: Decimal | None = None) -> bool:
        """Round at the shared comparison quantum, including converted unit precision."""
        other = type(self).model_validate(right)
        step = quantum if quantum is not None else max(self.quantum(), other.quantum())
        if not step.is_finite() or step <= 0:
            raise FHIRPathError("Comparison quantum must be finite and positive")
        with localcontext() as context:
            context.prec = (
                max(
                    context.prec,
                    len(self.root.as_tuple().digits),
                    len(right.as_tuple().digits),
                    self.root.adjusted() + 1,
                    right.adjusted() + 1,
                )
                + abs(step.adjusted())
                + 4
            )
            return (self.root / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) == (right / step).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
