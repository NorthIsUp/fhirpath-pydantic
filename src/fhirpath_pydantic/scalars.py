"""Native scalar functions with explicit conversions and no serialization."""

import math
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, localcontext

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
        value = one(focus)
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
                            result = TemporalValue.from_text(value.split("T")[0], "Date").native()
                        case TemporalValue() if value.kind != "Time":
                            result = TemporalValue(
                                kind="Date", year=value.year, month=value.month, day=value.day
                            ).native()
                        case _:
                            pass
                case "DateTime":
                    if isinstance(value, datetime) or isinstance(value, TemporalValue) and value.kind == "DateTime":
                        result = value
                    elif isinstance(value, str):
                        result = TemporalValue.from_text(value, "DateTime").native()
                    elif isinstance(value, date) or isinstance(value, TemporalValue) and value.kind == "Date":
                        temporal = TemporalValue.from_value(value)
                        assert temporal is not None
                        result = TemporalValue(
                            kind="DateTime", year=temporal.year, month=temporal.month, day=temporal.day
                        ).native()
                case "Time":
                    if isinstance(value, time) or isinstance(value, TemporalValue) and value.kind == "Time":
                        result = value
                    elif isinstance(value, str):
                        result = TemporalValue.from_text(value, "Time").native()
                case _:
                    raise UnsupportedFeatureError(f"Unsupported conversion: {name}")
        except (ValueError, InvalidOperation):  # fmt: skip
            result = None
        return items(result is not None) if name.startswith("convertsTo") else items(result)

    def numeric(self, name: str, params: list[list[Item]]) -> list[Item]:
        """Apply numeric functions with Decimal precision and empty propagation."""
        focus = self.root
        if not focus:
            return []
        value = number(one(focus))
        try:
            match name:
                case "abs":
                    return items(abs(value))
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
                    if precision < 0:
                        raise FHIRPathError("round() precision cannot be negative")
                    return items(value.quantize(Decimal(1).scaleb(-precision), rounding="ROUND_HALF_UP"))
                case _:
                    raise UnsupportedFeatureError(f"Unsupported math function: {name}")
        except (InvalidOperation, ZeroDivisionError):  # fmt: skip
            return []

    def strings(self, name: str, params: list[list[Item]]) -> list[Item]:
        """Delegate checked singleton text transformations to the string owner."""
        focus = self.root
        required = params[:1] if name == "substring" else params
        if not focus or any(not parameter for parameter in required):
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
