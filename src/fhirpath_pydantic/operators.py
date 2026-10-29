"""FHIRPath singleton, equality and three-valued Boolean semantics."""

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import ConfigDict, RootModel

from fhirpath_pydantic.native import Item, items
from fhirpath_pydantic.types import FHIRPathError, UnsupportedFeatureError, Value


def one(collection: list[Item]) -> Value:
    """Require at most one value, retaining empty as None."""
    if len(collection) > 1:
        raise FHIRPathError("Expected a singleton collection")
    return collection[0].value if collection else None


def boolean(collection: list[Item]) -> bool | None:
    """FHIRPath singleton evaluation treats a non-Boolean singleton as true."""
    if not collection:
        return None
    value = one(collection)
    return value if isinstance(value, bool) else True


def number(value: Value) -> Decimal:
    """Normalize arithmetic without float rounding or Boolean coercion."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise FHIRPathError("Expected a numeric value")
    return Decimal(str(value))


def integer(collection: list[Item]) -> int:
    """Require an Integer singleton."""
    value = one(collection)
    if isinstance(value, bool) or not isinstance(value, int):
        raise FHIRPathError("Expected an Integer singleton")
    return value


def string(collection: list[Item]) -> str:
    """Require a String singleton."""
    if not isinstance(value := one(collection), str):
        raise FHIRPathError("Expected a String singleton")
    return value


def equal(left: Value, right: Value, *, equivalent: bool = False) -> bool:
    """Compare primitives without Python's True-equals-one coercion."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if equivalent and isinstance(left, str) and isinstance(right, str):
        return " ".join(left.split()).casefold() == " ".join(right.split()).casefold()
    if isinstance(left, bool):
        return left == right
    if isinstance(left, (int, float, Decimal)) and isinstance(right, (int, float, Decimal)):
        return number(left) == number(right)
    return left == right


def unique(collection: list[Item]) -> list[Item]:
    """Retain first occurrences using FHIRPath equality."""
    result: list[Item] = []
    for item in collection:
        if not any(equal(item.value, previous.value) for previous in result):
            result.append(item)
    return result


class ScalarValue(RootModel[Value]):
    """Typed scalar comparison behavior, independent of collection cardinality."""

    model_config = ConfigDict(frozen=True)

    def compare(self, b: Value) -> int:
        """Order compatible native scalar values without coercing Booleans."""
        a = self.root
        match a, b:
            case (bool(), _) | (_, bool()):
                raise FHIRPathError("Boolean values cannot be ordered")
            case ((int() | float() | Decimal()), (int() | float() | Decimal())):
                x, y = number(a), number(b)
                return (x > y) - (x < y)
            case str(), str():
                return (a > b) - (a < b)
            case datetime(), datetime():
                return (a > b) - (a < b)
            case date(), date() if not isinstance(a, datetime) and not isinstance(b, datetime):
                return (a > b) - (a < b)
            case time(), time():
                return (a > b) - (a < b)
            case _:
                raise FHIRPathError("Cannot order values of incompatible types")


def binary(operator: str, left: list[Item], right: list[Item]) -> list[Item]:
    """Apply a binary operator with FHIRPath empty-collection behavior."""
    if operator == "|":
        return unique([*left, *right])
    if operator in {"and", "or", "xor", "implies"}:
        a, b = boolean(left), boolean(right)
        match operator:
            case "and":
                return items(False if a is False or b is False else None if a is None or b is None else True)
            case "or":
                return items(True if a is True or b is True else None if a is None or b is None else False)
            case "xor":
                return items(None if a is None or b is None else a != b)
            case "implies":
                return items(True if a is False or b is True else None if a is None or b is None else b)
            case _:
                raise UnsupportedFeatureError(f"Unsupported Boolean operator: {operator}")
    if operator in {"~", "!~"}:
        remaining = list(right)
        equivalent = len(left) == len(right)
        for item in left:
            for index, other in enumerate(remaining):
                if equal(item.value, other.value, equivalent=True):
                    remaining.pop(index)
                    break
            else:
                equivalent = False
        return items(equivalent if operator == "~" else not equivalent)
    if operator == "&":
        return items((string(left) if left else "") + (string(right) if right else ""))
    if not left or not right:
        return items(False) if (operator == "in" and left) or (operator == "contains" and right) else []
    if operator in {"=", "!="}:
        same = len(left) == len(right) and all(equal(a.value, b.value) for a, b in zip(left, right, strict=False))
        return items(same if operator == "=" else not same)
    if operator in {"in", "contains"}:
        singleton, collection = (left, right) if operator == "in" else (right, left)
        value = one(singleton)
        return items(any(equal(value, other.value) for other in collection))
    a, b = one(left), one(right)
    if operator in {"<", "<=", ">", ">="}:
        comparison = ScalarValue.model_construct(root=a).compare(b)
        return items({"<": comparison < 0, "<=": comparison <= 0, ">": comparison > 0, ">=": comparison >= 0}[operator])
    if operator == "+" and isinstance(a, str) and isinstance(b, str):
        return items(a + b)
    x, y = number(a), number(b)
    if isinstance(a, int) and isinstance(b, int):
        match operator:
            case "+":
                return items(a + b)
            case "-":
                return items(a - b)
            case "*":
                return items(a * b)
            case "mod":
                return items((-1 if a < 0 else 1) * (abs(a) % abs(b))) if b else []
            case _:
                pass
    match operator:
        case "+":
            return items(x + y)
        case "-":
            return items(x - y)
        case "*":
            return items(x * y)
        case "/":
            return items(x / y) if y else []
        case "div":
            return items(int(x / y)) if y else []
        case "mod":
            return items(x % y) if y else []
        case _:
            raise UnsupportedFeatureError(f"Unsupported operator: {operator}")
