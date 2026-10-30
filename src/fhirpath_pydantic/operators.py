"""FHIRPath singleton, equality and three-valued Boolean semantics."""

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, RootModel

from fhirpath_pydantic.decimal_value import DecimalValue
from fhirpath_pydantic.native import Item, ModelPlan, NativeCollection, items
from fhirpath_pydantic.quantities import QuantityComparison, QuantityValue
from fhirpath_pydantic.temporal import TemporalValue
from fhirpath_pydantic.types import Collection, FHIRPathError, UnsupportedFeatureError, Value


def one(collection: list[Item]) -> Value:
    """Require at most one value, retaining empty as None."""
    return Item.singleton(collection)


def boolean(collection: list[Item]) -> bool | None:
    """FHIRPath singleton evaluation treats a non-Boolean singleton as true."""
    return Item.boolean(collection)


def number(value: Value) -> Decimal:
    """Normalize arithmetic without float rounding or Boolean coercion."""
    return ScalarValue.model_construct(root=value).number()


def integer(collection: list[Item]) -> int:
    """Require an Integer singleton."""
    return Item.integer(collection)


def string(collection: list[Item]) -> str:
    """Require a String singleton."""
    return Item.string(collection)


def equal(left: Value, right: Value, *, equivalent: bool = False) -> bool | None:
    """Compare primitives without Python's True-equals-one coercion."""
    return ScalarValue.model_construct(root=left).equals(right, equivalent=equivalent)


def unique(collection: list[Item]) -> list[Item]:
    """Retain first occurrences using FHIRPath equality."""
    return OperatorCollection.model_construct(root=collection).unique()


class ScalarValue(RootModel[Value]):
    """Typed scalar comparison behavior, independent of collection cardinality."""

    model_config = ConfigDict(frozen=True)

    def number(self) -> Decimal:
        """Normalize a numeric primitive without Boolean or float rounding coercion."""
        value = self.root
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise FHIRPathError("Expected a numeric value")
        return Decimal(str(value))

    def decimal_equivalent(self, right: Value) -> bool:
        """Compare numeric values through the finite Decimal precision owner."""
        return DecimalValue.model_validate(self.number()).equivalent(number(right))

    def properties(self, *, ignore_id: bool = False) -> dict[str, Collection] | None:
        """Read complex child collections through aliases without dumping native models."""
        value = self.root
        result: dict[str, Collection] = {}
        if isinstance(value, BaseModel):
            item = Item.from_native(value)
            for name in ModelPlan.from_model(type(value)).children:
                if ignore_id and name == "id":
                    continue
                children = [child.system_value() for child in item.member(name).root]
                if children:
                    result[name] = children
            return result
        if isinstance(value, dict):
            for name, child in value.items():
                if name == "resourceType" or ignore_id and name == "id":
                    continue
                children = [item.system_value() for item in items(child)]
                if children:
                    result[name] = children
            return result
        return None

    def equals(self, right: Value, *, equivalent: bool = False) -> bool | None:
        """Compare compatible quantities, temporal values and primitives."""
        left = self.root
        if isinstance(left, bool) != isinstance(right, bool):
            return False
        if QuantityValue.is_quantity(left) or QuantityValue.is_quantity(right):
            return QuantityComparison(left=left, right=right).equals(equivalent=equivalent)
        if (a_time := TemporalValue.from_value(left)) is not None:
            b_time = TemporalValue.from_value(right)
            return a_time.equals(b_time, equivalent=equivalent) if b_time is not None else False
        if TemporalValue.from_value(right) is not None:
            return False
        if equivalent and isinstance(left, str) and isinstance(right, str):
            return " ".join(left.split()).casefold() == " ".join(right.split()).casefold()
        if isinstance(left, bool):
            return left == right
        if isinstance(left, (int, float, Decimal)) and isinstance(right, (int, float, Decimal)):
            return self.decimal_equivalent(right) if equivalent else self.number() == number(right)
        if isinstance(left, list) and isinstance(right, list):
            if not left and not right:
                return True
            result = OperatorCollection.model_construct(root=items(left)).binary(
                "~" if equivalent else "=", items(right)
            )
            return Item.boolean(result)
        if isinstance(left, (BaseModel, dict)) and isinstance(right, (BaseModel, dict)):
            left_type, right_type = Item.from_native(left).resource_type(), Item.from_native(right).resource_type()
            if left_type != right_type:
                return False
            ignore_id = equivalent and left_type is not None
            left_properties = self.properties(ignore_id=ignore_id)
            right_properties = type(self).model_construct(root=right).properties(ignore_id=ignore_id)
            assert left_properties is not None and right_properties is not None
            if left_properties.keys() != right_properties.keys():
                return False
            comparisons = [
                type(self).model_construct(root=children).equals(right_properties[name], equivalent=equivalent)
                for name, children in left_properties.items()
            ]
            return False if False in comparisons else None if None in comparisons else True
        return left == right

    def compare(self, b: Value) -> int | None:
        """Order compatible native scalar values without coercing Booleans."""
        a = self.root
        if QuantityValue.is_quantity(a) or QuantityValue.is_quantity(b):
            return QuantityComparison(left=a, right=b).compare()
        if (a_time := TemporalValue.from_value(a)) is not None and (b_time := TemporalValue.from_value(b)) is not None:
            return a_time.compare(b_time)
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


class OperatorCollection(NativeCollection):
    """Collection equality, set membership and binary operations own their focus."""

    def unique(self) -> list[Item]:
        """Retain first occurrences using FHIRPath scalar equality."""
        collection = self.root
        result: list[Item] = []
        for item in collection:
            if not any(equal(item.system_value(), previous.system_value()) for previous in result):
                result.append(item)
        return result

    def binary(self, operator: str, right: list[Item]) -> list[Item]:
        """Apply binary semantics to this collection and the right operand."""
        left = self.root
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
                    if equal(item.system_value(), other.system_value(), equivalent=True) is True:
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
            if len(left) != len(right):
                return items(operator == "!=")
            comparisons = [equal(a.system_value(), b.system_value()) for a, b in zip(left, right, strict=True)]
            if any(value is False for value in comparisons):
                same: bool | None = False
            else:
                same = None if any(value is None for value in comparisons) else True
            return items(same if operator == "=" else not same if same is not None else None)
        if operator in {"in", "contains"}:
            singleton, collection = (left, right) if operator == "in" else (right, left)
            value = one(singleton)
            return items(any(equal(value, other.system_value()) for other in collection))
        a, b = one(left), one(right)
        if a is None or b is None:
            return []
        if operator in {"<", "<=", ">", ">="}:
            comparison = ScalarValue.model_construct(root=a).compare(b)
            if comparison is None:
                return []
            return items(
                {"<": comparison < 0, "<=": comparison <= 0, ">": comparison > 0, ">=": comparison >= 0}[operator]
            )
        if operator == "+" and isinstance(a, str) and isinstance(b, str):
            return items(a + b)
        if (temporal := TemporalValue.from_value(a)) is not None:
            quantity = QuantityValue.operand(b)
            if operator not in {"+", "-"} or quantity is None:
                raise FHIRPathError("Temporal arithmetic requires addition/subtraction of a time quantity")
            return items(temporal.shifted(quantity, subtract=operator == "-"))
        if QuantityValue.is_quantity(a) or QuantityValue.is_quantity(b):
            left_quantity, right_quantity = QuantityValue.operand(a), QuantityValue.operand(b)
            if left_quantity is None or right_quantity is None:
                return []
            return items(left_quantity.arithmetic(operator, right_quantity))
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


def binary(operator: str, left: list[Item], right: list[Item]) -> list[Item]:
    """Apply a binary operator with FHIRPath empty-collection behavior."""
    return OperatorCollection.model_construct(root=left).binary(operator, right)
