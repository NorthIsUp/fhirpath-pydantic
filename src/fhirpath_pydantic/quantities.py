"""Validated system quantities and unit algebra, independent of resource serialization."""

import re
from decimal import Decimal, DecimalException
from functools import lru_cache
from typing import ClassVar, Self, override

from fhir.resources.quantity import Quantity as R5Quantity
from fhir.resources.R4B.quantity import Quantity as R4BQuantity
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

from fhirpath_pydantic.decimal_value import DecimalValue
from fhirpath_pydantic.types import FHIRPathError, Value


class UnitTerms(RootModel[dict[str, int]]):
    """Case-sensitive symbolic factors of a product or quotient of units."""

    model_config = ConfigDict(frozen=True)

    @field_validator("root")
    @classmethod
    def without_zero_powers(cls, value: dict[str, int]) -> dict[str, int]:
        """Cancelled unit factors have no effect on a dimension."""
        return {symbol: power for symbol, power in value.items() if power != 0}

    @classmethod
    def from_code(cls, code: str) -> Self:
        """Read UCUM products, quotients and integer powers without changing case."""
        terms: dict[str, int] = {}
        for index, side in enumerate(code.split("/")):
            for token in side.split("."):
                if token == "1":
                    continue
                if (match := re.fullmatch(r"(\[[^\]]+\]|[A-Za-z%][A-Za-z_]*(?:\[[^\]]+\])?)(-?\d+)?", token)) is None:
                    # Unrecognized valid UCUM codes remain opaque and exact-match only.
                    return cls.model_validate({code: 1})
                symbol, exponent = match.groups()
                power = int(exponent or "1") * (1 if index == 0 else -1)
                terms[symbol] = terms.get(symbol, 0) + power
        return cls.model_validate(terms)

    def combined(self, other: UnitTerms, *, divide: bool = False) -> Self:
        """Add or subtract symbolic exponents for multiplication or division."""
        terms = dict(self.root)
        for symbol, power in other.root.items():
            terms[symbol] = terms.get(symbol, 0) + (-power if divide else power)
        return self.model_validate(terms)

    def code(self) -> str:
        """Render a unit expression, never a FHIRPath query."""
        return ".".join(symbol if power == 1 else f"{symbol}{power}" for symbol, power in self.root.items()) or "1"


class QuantityUnit(BaseModel):
    """A unit's dimensions and exact scale relative to base SI units."""

    model_config = ConfigDict(frozen=True)
    symbol: str
    dimensions: UnitTerms
    factor: Decimal = Field(gt=0, allow_inf_nan=False)

    CALENDAR_TO_UCUM: ClassVar[dict[str, str]] = {
        "year": "a",
        "month": "mo",
        "week": "wk",
        "day": "d",
        "hour": "h",
        "minute": "min",
        "second": "s",
        "millisecond": "ms",
    }
    FHIR_CALENDAR: ClassVar[dict[str, str]] = {
        "a": "year",
        "mo": "month",
        "d": "day",
        "h": "hour",
        "min": "minute",
        "s": "second",
    }
    ATOMS: ClassVar[dict[str, tuple[dict[str, int], Decimal]]] = {
        "m": ({"length": 1}, Decimal(1)),
        "cm": ({"length": 1}, Decimal("0.01")),
        "mm": ({"length": 1}, Decimal("0.001")),
        "km": ({"length": 1}, Decimal(1000)),
        "um": ({"length": 1}, Decimal("0.000001")),
        "nm": ({"length": 1}, Decimal("0.000000001")),
        "[in_i]": ({"length": 1}, Decimal("0.0254")),
        "[ft_i]": ({"length": 1}, Decimal("0.3048")),
        "g": ({"mass": 1}, Decimal(1)),
        "kg": ({"mass": 1}, Decimal(1000)),
        "mg": ({"mass": 1}, Decimal("0.001")),
        "ug": ({"mass": 1}, Decimal("0.000001")),
        "ng": ({"mass": 1}, Decimal("0.000000001")),
        "[lb_av]": ({"mass": 1}, Decimal("453.59237")),
        "lbs": ({"mass": 1}, Decimal("453.59237")),
        "s": ({"time": 1}, Decimal(1)),
        "ms": ({"time": 1}, Decimal("0.001")),
        "min": ({"time": 1}, Decimal(60)),
        "h": ({"time": 1}, Decimal(3600)),
        "d": ({"time": 1}, Decimal(86400)),
        "wk": ({"time": 1}, Decimal(604800)),
        "a": ({"time": 1}, Decimal(31557600)),
        "mo": ({"time": 1}, Decimal(2629800)),
        "year": ({"time": 1}, Decimal(31536000)),
        "month": ({"time": 1}, Decimal(2592000)),
        "week": ({"time": 1}, Decimal(604800)),
        "day": ({"time": 1}, Decimal(86400)),
        "hour": ({"time": 1}, Decimal(3600)),
        "minute": ({"time": 1}, Decimal(60)),
        "second": ({"time": 1}, Decimal(1)),
        "millisecond": ({"time": 1}, Decimal("0.001")),
        "L": ({"length": 3}, Decimal("0.001")),
        "l": ({"length": 3}, Decimal("0.001")),
        "mL": ({"length": 3}, Decimal("0.000001")),
        "ml": ({"length": 3}, Decimal("0.000001")),
        "dL": ({"length": 3}, Decimal("0.0001")),
        "%": ({}, Decimal("0.01")),
    }

    @classmethod
    def normalize(cls, unit: str) -> str:
        """Normalize calendar plurals while preserving UCUM's case sensitivity."""
        if not unit or any(char.isspace() or char in "'\"" for char in unit):
            raise ValueError("A quantity unit must be nonempty and contain no whitespace or quotes")
        singular = unit.removesuffix("s")
        return singular if singular in cls.CALENDAR_TO_UCUM else unit

    @classmethod
    @lru_cache(maxsize=256)
    def from_code(cls, code: str) -> QuantityUnit:
        """Resolve known conversions; retain other codes as opaque dimensions."""
        code = cls.normalize(code)
        dimensions: dict[str, int] = {}
        factor = Decimal(1)
        for symbol, power in UnitTerms.from_code(code).root.items():
            atom_dimensions, atom_factor = cls.ATOMS.get(symbol, ({f"opaque:{symbol}": 1}, Decimal(1)))
            factor *= atom_factor**power
            for dimension, exponent in atom_dimensions.items():
                dimensions[dimension] = dimensions.get(dimension, 0) + exponent * power
        return cls(symbol=code, dimensions=UnitTerms.model_validate(dimensions), factor=factor)

    def is_calendar(self) -> bool:
        """Calendar durations and definite UCUM durations have distinct semantics."""
        return self.symbol in self.CALENDAR_TO_UCUM


class QuantityValue(BaseModel):
    """FHIRPath System.Quantity, with Decimal values and validated unit syntax."""

    model_config = ConfigDict(frozen=True)
    value: Decimal = Field(allow_inf_nan=False)
    unit: str = "1"

    @field_validator("unit")
    @classmethod
    def valid_unit(cls, unit: str) -> str:
        """Validate and normalize units at every Pydantic input boundary."""
        return QuantityUnit.normalize(unit)

    @classmethod
    def from_text(cls, text: str) -> Self | None:
        """Parse only quantity text, never interpolate values into an expression."""
        match = re.fullmatch(r"(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?:'(?P<unit>[^']+)'|(?P<calendar>[A-Za-z]+))?", text)
        if match is None:
            return None
        unit = match["unit"] or match["calendar"] or "1"
        if match["calendar"] and QuantityUnit.normalize(unit) not in QuantityUnit.CALENDAR_TO_UCUM:
            return None
        return cls.model_validate({"value": match["value"], "unit": unit})

    @classmethod
    def is_quantity(cls, value: Value) -> bool:
        """Recognize system quantities and both supported native FHIR releases."""
        return isinstance(value, (cls, R4BQuantity, R5Quantity))

    @classmethod
    def from_value(cls, value: Value) -> Self | None:
        """Apply FHIRPath's explicit numeric, Boolean, text and native conversions."""
        if isinstance(value, cls):
            return value
        match value:
            case bool():
                return cls(value=Decimal(int(value)))
            case int() | float() | Decimal():
                return cls(value=Decimal(str(value)))
            case str():
                return cls.from_text(value)
            case R4BQuantity() | R5Quantity():
                return cls.from_fhir(value)
            case _:
                return None

    @classmethod
    def from_fhir(cls, value: R4BQuantity | R5Quantity) -> Self | None:
        """Map UCUM-coded FHIR quantities without dumping or modifying the model."""
        if value.system != "http://unitsofmeasure.org" or value.code is None or value.value is None:
            return None
        if value.comparator is not None:
            raise FHIRPathError("Cannot convert a FHIR Quantity with a comparator to an exact quantity")
        unit = QuantityUnit.FHIR_CALENDAR.get(value.code, value.code)
        return cls(value=value.value, unit=unit)

    @classmethod
    def operand(cls, value: Value) -> Self | None:
        """Implicit arithmetic conversion excludes String and Boolean coercion."""
        if cls.is_quantity(value) or isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            return cls.from_value(value)
        return None

    def convert_to(self, unit: str) -> QuantityValue | None:
        """Convert compatible dimensions while keeping decimal precision."""
        unit = QuantityUnit.normalize(unit)
        if unit == self.unit:
            return self
        if self.unit == "year" and unit == "month":
            return self.model_validate({"value": self.value * 12, "unit": unit})
        if self.unit == "month" and unit == "year":
            return self.model_validate({"value": self.value / 12, "unit": unit})
        source_unit = self.unit
        target_unit = unit
        source = QuantityUnit.from_code(source_unit)
        target = QuantityUnit.from_code(target_unit)
        if source.is_calendar() != target.is_calendar():
            source_unit = QuantityUnit.CALENDAR_TO_UCUM.get(source_unit, source_unit)
            target_unit = QuantityUnit.CALENDAR_TO_UCUM.get(target_unit, target_unit)
            source, target = QuantityUnit.from_code(source_unit), QuantityUnit.from_code(target_unit)
        if source.dimensions != target.dimensions:
            return None
        return self.model_validate({"value": self.value * source.factor / target.factor, "unit": unit})

    def comparable(self, other: QuantityValue, *, equivalent: bool = False) -> bool:
        """Require compatible dimensions and respect calendar-versus-definite units."""
        left, right = QuantityUnit.from_code(self.unit), QuantityUnit.from_code(other.unit)
        if left.dimensions != right.dimensions:
            return False
        if not equivalent and left.is_calendar() != right.is_calendar():
            calendar = self.unit if left.is_calendar() else other.unit
            if calendar not in {"second", "millisecond"}:
                return False
        return True

    def compare(self, other: QuantityValue, *, equivalent: bool = False) -> int | None:
        """Compare in a common unit, returning None when units are incomparable."""
        if not self.comparable(other, equivalent=equivalent):
            return None
        converted = other.convert_to(self.unit)
        if converted is None:
            return None
        return (self.value > converted.value) - (self.value < converted.value)

    def equivalent(self, other: QuantityValue) -> bool:
        """Shift original comparison precision into the most granular common unit."""
        if not self.comparable(other, equivalent=True):
            return False
        left_unit, right_unit = QuantityUnit.from_code(self.unit), QuantityUnit.from_code(other.unit)
        unit = self.unit if left_unit.factor <= right_unit.factor else other.unit
        left, right = self.convert_to(unit), other.convert_to(unit)
        left_quantum = type(self)(value=DecimalValue.model_validate(self.value).quantum(), unit=self.unit).convert_to(
            unit
        )
        right_quantum = type(self)(
            value=DecimalValue.model_validate(other.value).quantum(), unit=other.unit
        ).convert_to(unit)
        if left is None or right is None or left_quantum is None or right_quantum is None:
            return False
        return DecimalValue.model_validate(left.value).equivalent(
            right.value, quantum=max(left_quantum.value, right_quantum.value)
        )

    def equals(self, other: QuantityValue, *, equivalent: bool = False) -> bool | None:
        """Calendar and definite durations above seconds are unequal, not identical."""
        if equivalent:
            return self.equivalent(other)
        left, right = QuantityUnit.from_code(self.unit), QuantityUnit.from_code(other.unit)
        if (
            left.is_calendar() != right.is_calendar()
            and not self.comparable(other)
            and left.dimensions == right.dimensions
        ):
            return False
        comparison = self.compare(other, equivalent=equivalent)
        return comparison == 0 if comparison is not None else None

    def arithmetic(self, operator: str, other: QuantityValue) -> QuantityValue | None:
        """Add or subtract in the more granular unit; compose products and quotients."""
        try:
            match operator:
                case "+" | "-":
                    if not self.comparable(other):
                        return None
                    left_unit, right_unit = QuantityUnit.from_code(self.unit), QuantityUnit.from_code(other.unit)
                    unit = self.unit if left_unit.factor <= right_unit.factor else other.unit
                    left, right = self.convert_to(unit), other.convert_to(unit)
                    if left is None or right is None:
                        return None
                    value = left.value + right.value if operator == "+" else left.value - right.value
                    return self.model_validate({"value": value, "unit": unit})
                case "*" | "/":
                    if operator == "/" and other.value == 0:
                        return None
                    unit = (
                        UnitTerms.from_code(self.unit)
                        .combined(UnitTerms.from_code(other.unit), divide=operator == "/")
                        .code()
                    )
                    value = self.value * other.value if operator == "*" else self.value / other.value
                    return self.model_validate({"value": value, "unit": unit})
                case _:
                    raise FHIRPathError("Quantity arithmetic supports +, -, * and / only")
        except DecimalException:
            return None

    def absolute(self) -> Self:
        """Absolute magnitude preserves the validated unit and exact Decimal digits."""
        return self.model_copy(update={"value": self.value.copy_abs()})

    def negated(self) -> Self:
        """Unary negation retains the exact validated unit."""
        return self.model_copy(update={"value": -self.value})

    @override
    def __str__(self) -> str:
        number = format(self.value.normalize(), "f")
        return f"{number} '{self.unit}'"


class QuantityComparison(BaseModel):
    """Quantity operands retain native unit text when System conversion is unavailable."""

    model_config = ConfigDict(frozen=True)
    left: Value
    right: Value

    def native_values(self) -> tuple[Decimal, Decimal] | None:
        """Match native unit labels without treating display text as UCUM codes."""
        left, right = self.left, self.right
        if not isinstance(left, (R4BQuantity, R5Quantity)) or not isinstance(right, (R4BQuantity, R5Quantity)):
            return None
        if left.comparator is not None or right.comparator is not None:
            raise FHIRPathError("Cannot compare a FHIR Quantity with a comparator as an exact quantity")
        if left.unit is None and (left.code is not None or right.code is not None):
            return None
        if left.unit != right.unit or left.value is None or right.value is None:
            return None
        return left.value, right.value

    def equals(self, *, equivalent: bool = False) -> bool | None:
        """Use UCUM semantics when possible and matching native labels otherwise."""
        left, right = QuantityValue.operand(self.left), QuantityValue.operand(self.right)
        if left is not None and right is not None:
            return left.equals(right, equivalent=equivalent)
        if (values := self.native_values()) is not None:
            a, b = values
            return DecimalValue.model_validate(a).equivalent(b) if equivalent else a == b
        native = isinstance(self.left, (R4BQuantity, R5Quantity)) and isinstance(self.right, (R4BQuantity, R5Quantity))
        return None if native and not equivalent else False

    def compare(self) -> int | None:
        """Only order quantities with compatible coded units or identical native labels."""
        left, right = QuantityValue.operand(self.left), QuantityValue.operand(self.right)
        if left is not None and right is not None:
            return left.compare(right)
        if (values := self.native_values()) is not None:
            a, b = values
            return (a > b) - (a < b)
        return None
