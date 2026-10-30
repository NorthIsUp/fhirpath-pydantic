"""Decimal comparison precision is shared by scalar and quantity values."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

from pydantic import ConfigDict, RootModel

from fhirpath_pydantic.types import FHIRPathError


class DecimalValue(RootModel[Decimal]):
    """A finite decimal whose comparison precision does not mutate its value."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

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
