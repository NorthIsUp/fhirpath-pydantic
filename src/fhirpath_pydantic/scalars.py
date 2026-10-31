"""Native scalar functions with explicit conversions and no serialization."""

import math
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, localcontext

from fhirpath_pydantic.decimal_value import DecimalValue
from fhirpath_pydantic.native import Item, NativeCollection, items
from fhirpath_pydantic.operators import integer, number, one, string
from fhirpath_pydantic.quantities import QuantityValue
from fhirpath_pydantic.temporal import TemporalValue
from fhirpath_pydantic.text import StringValue
from fhirpath_pydantic.type_info import TypeInfo
from fhirpath_pydantic.types import FHIRPathError, UnsupportedFeatureError, Value


def is_type(value: Value, name: str) -> bool:
    """Test FHIR or System types using native Python and FHIR model types."""
    return TypeInfo.from_value(value).matches(name, value)


class PrimitiveCollection(NativeCollection):
    """Singleton primitive conversions and functions retain collection cardinality."""

    def convert(self, name: str) -> list[Item]:
        """Convert a singleton or report conversion availability."""
        focus = self.root
        if not focus:
            return []
        if (value := one(focus)) is None:
            return []
        target = name.removeprefix("convertsTo").removeprefix("to")
        result: Value = None
        try:
            match target:
                case "String":
                    match value:
                        case QuantityValue() | TemporalValue():
                            result = str(value)
                        case bool():
                            result = "true" if value else "false"
                        case date() | time():
                            result = value.isoformat()
                        case str() | int() | float() | Decimal():
                            result = str(value)
                        case _:
                            pass
                case "Boolean":
                    if isinstance(value, bool):
                        result = value
                    elif isinstance(value, (int, float, Decimal)) and value in (0, 1):
                        result = bool(value)
                    elif isinstance(value, str):
                        normalized = value.casefold()
                        if normalized in {"true", "t", "yes", "y", "1", "1.0"}:
                            result = True
                        elif normalized in {"false", "f", "no", "n", "0", "0.0"}:
                            result = False
                case "Integer":
                    if isinstance(value, (bool, int)) or isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value):
                        result = int(value)
                case "Decimal":
                    if isinstance(value, (str, int, float, Decimal)) and (
                        not isinstance(value, str) or re.fullmatch(r"[+-]?\d+(\.\d+)?", value)
                    ):
                        result = Decimal(int(value)) if isinstance(value, bool) else Decimal(str(value))
                case "Date":
                    match value:
                        case datetime():
                            result = value.date()
                        case date():
                            result = value
                        case str():
                            result = TemporalValue.from_text(value.split("T")[0], "Date")
                        case TemporalValue() if value.kind != "Time":
                            result = TemporalValue(kind="Date", year=value.year, month=value.month, day=value.day)
                        case _:
                            pass
                case "DateTime":
                    if isinstance(value, datetime) or isinstance(value, TemporalValue) and value.kind == "DateTime":
                        result = focus[0].temporal_value()
                    elif isinstance(value, str):
                        result = TemporalValue.from_text(value, "DateTime")
                    elif isinstance(value, date) or isinstance(value, TemporalValue) and value.kind == "Date":
                        temporal = TemporalValue.from_value(value)
                        assert temporal is not None
                        result = TemporalValue(
                            kind="DateTime", year=temporal.year, month=temporal.month, day=temporal.day
                        )
                case "Time":
                    if isinstance(value, time) or isinstance(value, TemporalValue) and value.kind == "Time":
                        result = focus[0].temporal_value()
                    elif isinstance(value, str):
                        result = TemporalValue.from_text(value, "Time")
                case _:
                    raise UnsupportedFeatureError(f"Unsupported conversion: {name}")
        except (ValueError, InvalidOperation):  # fmt: skip
            result = None
        if name.startswith("convertsTo"):
            return items(result is not None)
        return [Item.from_temporal(result)] if isinstance(result, TemporalValue) else items(result)

    def numeric(self, name: str, params: list[list[Item]]) -> list[Item]:
        """Apply numeric functions with Decimal precision and empty propagation."""
        focus = self.root
        if not focus:
            return []
        if (native := one(focus)) is None:
            return []
        if name == "abs" and isinstance(native, int) and not isinstance(native, bool):
            return items(abs(native))
        if name == "abs" and QuantityValue.is_quantity(native):
            quantity = QuantityValue.operand(native)
            return items(quantity.absolute() if quantity is not None else None)
        value = number(native)
        try:
            match name:
                case "abs":
                    return items(value.copy_abs())
                case "ceiling":
                    return items(math.ceil(value))
                case "floor":
                    return items(math.floor(value))
                case "truncate":
                    return items(int(value))
                case "sqrt":
                    return items(value.sqrt())
                case "exp":
                    return items(value.exp())
                case "ln":
                    return items(value.ln()) if value > 0 else []
                case "power":
                    return items(value ** number(one(params[0]))) if params[0] else []
                case "log":
                    if not params[0]:
                        return []
                    base = number(one(params[0]))
                    if value <= 0 or base <= 0 or base == 1:
                        return []
                    with localcontext() as context:
                        context.prec += 10
                        result = value.ln() / base.ln()
                    return items(+result)
                case "round":
                    precision = integer(params[0]) if params and params[0] else 0
                    return items(DecimalValue.model_validate(value).rounded(precision))
                case _:
                    raise UnsupportedFeatureError(f"Unsupported math function: {name}")
        except (InvalidOperation, ZeroDivisionError):  # fmt: skip
            return []

    def joined(self, separator: list[Item] | None = None) -> list[Item]:
        """Join present primitive strings without manufacturing a value for empty input."""
        if not self.root or separator is not None and not separator:
            return []
        delimiter = string(separator) if separator is not None else ""
        parts: list[str] = []
        for item in self.root:
            value = item.system_value()
            if value is None:
                continue
            if not isinstance(value, str):
                raise FHIRPathError("join() requires String values")
            parts.append(value)
        return items(delimiter.join(parts)) if parts else []

    def strings(self, name: str, params: list[list[Item]]) -> list[Item]:
        """Delegate checked singleton text transformations to the string owner."""
        focus = self.root
        required = params[:1] if name == "substring" else params
        if one(focus) is None or any(one(parameter) is None for parameter in required):
            return []
        return items(StringValue.model_validate(string(focus)).transform(name, params))


def convert(name: str, focus: list[Item]) -> list[Item]:
    """Convert primitives through their native collection owner."""
    return PrimitiveCollection.model_construct(root=focus).convert(name)


def numeric(name: str, focus: list[Item], params: list[list[Item]]) -> list[Item]:
    """Apply numeric functions through their native collection owner."""
    return PrimitiveCollection.model_construct(root=focus).numeric(name, params)


def strings(name: str, focus: list[Item], params: list[list[Item]]) -> list[Item]:
    """Apply text functions through their native collection owner."""
    return PrimitiveCollection.model_construct(root=focus).strings(name, params)
