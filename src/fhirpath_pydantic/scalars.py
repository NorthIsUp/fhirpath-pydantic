"""Native scalar functions with explicit conversions and no serialization."""

import math
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, localcontext

from pydantic import BaseModel

from fhirpath_pydantic.native import Item, items, resource_type
from fhirpath_pydantic.operators import integer, number, one, string
from fhirpath_pydantic.quantities import QuantityValue
from fhirpath_pydantic.types import FHIRPathError, UnsupportedFeatureError, Value


def is_type(value: Value, name: str) -> bool:
    """Test FHIR or System types using native Python and FHIR model types."""
    if isinstance(value, QuantityValue):
        return name in {"Quantity", "System.Quantity"}
    if QuantityValue.is_quantity(value) and name == "System.Quantity":
        return False
    name = name.removeprefix("FHIR.").removeprefix("System.")
    match name:
        case "Boolean" | "boolean":
            return isinstance(value, bool)
        case "Integer" | "integer" | "positiveInt" | "unsignedInt" | "Integer64" | "integer64":
            return isinstance(value, int) and not isinstance(value, bool)
        case "Decimal" | "decimal":
            return isinstance(value, (float, Decimal))
        case "String" | "string" | "code" | "uri" | "url" | "id" | "canonical" | "markdown" | "oid" | "uuid":
            return isinstance(value, str)
        case "Date" | "date":
            return isinstance(value, date) and not isinstance(value, datetime)
        case "DateTime" | "dateTime" | "instant":
            return isinstance(value, datetime)
        case "Time" | "time":
            return isinstance(value, time)
        case _:
            return (
                any(base.__name__ == name for base in type(value).__mro__)
                if isinstance(value, BaseModel)
                else resource_type(value) == name
            )


def convert(name: str, focus: list[Item]) -> list[Item]:
    """Convert one primitive, returning empty when conversion fails."""
    if not focus:
        return []
    value = one(focus)
    target = name.removeprefix("convertsTo").removeprefix("to")
    result: Value = None
    try:
        match target:
            case "String":
                match value:
                    case QuantityValue():
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
                    case str() if len(value) == 10:
                        result = date.fromisoformat(value)
                    case _:
                        pass
            case "DateTime":
                if isinstance(value, datetime):
                    result = value
                elif isinstance(value, str):
                    result = datetime.fromisoformat(value)
            case "Time":
                if isinstance(value, time):
                    result = value
                elif isinstance(value, str):
                    result = time.fromisoformat(value.removeprefix("T"))
            case _:
                raise UnsupportedFeatureError(f"Unsupported conversion: {name}")
    except (ValueError, InvalidOperation):  # fmt: skip
        result = None
    return items(result is not None) if name.startswith("convertsTo") else items(result)


def numeric(name: str, focus: list[Item], params: list[list[Item]]) -> list[Item]:
    """Apply Decimal arithmetic, preserving undefined results as empty."""
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
                return items(value ** number(one(params[0])))
            case "log":
                base = number(one(params[0]))
                if value <= 0 or base <= 0 or base == 1:
                    return []
                with localcontext() as context:
                    context.prec += 10
                    result = value.ln() / base.ln()
                return items(+result)
            case "round":
                precision = integer(params[0]) if params else 0
                if precision < 0:
                    raise FHIRPathError("round() precision cannot be negative")
                return items(value.quantize(Decimal(1).scaleb(-precision), rounding="ROUND_HALF_UP"))
            case _:
                raise UnsupportedFeatureError(f"Unsupported math function: {name}")
    except (InvalidOperation, ZeroDivisionError):  # fmt: skip
        return []


def strings(name: str, focus: list[Item], params: list[list[Item]]) -> list[Item]:
    """Apply string functions with strict singleton arguments."""
    if not focus or any(not parameter for parameter in params):
        return []
    value = string(focus)
    match name:
        case "length":
            return items(len(value))
        case "upper":
            return items(value.upper())
        case "lower":
            return items(value.lower())
        case "toChars":
            return items(list(value))
        case "substring":
            start = integer(params[0])
            if start < 0 or start >= len(value):
                return []
            length = integer(params[1]) if len(params) > 1 else len(value)
            return items(value[start : start + max(length, 0)])
        case "startsWith":
            return items(value.startswith(string(params[0])))
        case "endsWith":
            return items(value.endswith(string(params[0])))
        case "contains":
            return items(string(params[0]) in value)
        case "indexOf":
            return items(value.find(string(params[0])))
        case "matches":
            return items(re.search(string(params[0]), value) is not None)
        case "replace":
            return items(value.replace(string(params[0]), string(params[1])))
        case "replaceMatches":
            return items(re.sub(string(params[0]), string(params[1]), value))
        case "split":
            separator = string(params[0])
            return [Item.model_construct(value=part) for part in (value.split(separator) if separator else value)]
        case _:
            raise UnsupportedFeatureError(f"Unsupported string function: {name}")
