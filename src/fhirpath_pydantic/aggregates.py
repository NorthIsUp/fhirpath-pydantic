"""Native collection aggregates owned by a Pydantic collection model."""

from decimal import Decimal
from typing import Literal

from fhirpath_pydantic.native import Item, NativeCollection, items
from fhirpath_pydantic.operators import ScalarValue, binary
from fhirpath_pydantic.quantities import QuantityValue
from fhirpath_pydantic.types import FHIRPathError


class AggregateCollection(NativeCollection):
    """A native collection's numeric reductions and ordered extrema."""

    def aggregate(self, operation: Literal["sum", "avg", "min", "max"]) -> NativeCollection:
        """Reduce native values without dumping models or erasing quantity units."""
        present = [item for item in self.root if item.value is not None]
        if not present:
            return NativeCollection.from_value(0 if operation == "sum" else None)
        if operation in {"sum", "avg"}:
            for item in present:
                value = item.value
                if isinstance(value, bool) or not (
                    isinstance(value, (int, float, Decimal)) or QuantityValue.is_quantity(value)
                ):
                    raise FHIRPathError("Numeric aggregates require numbers or quantities")
            total: list[Item] = [present[0]]
            for item in present[1:]:
                total = binary("+", total, [item])
                if not total:
                    return NativeCollection.model_construct(root=[])
            if operation == "avg":
                total = binary("/", total, items(len(present)))
            return NativeCollection.model_construct(root=total)
        best = present[0]
        for item in present[1:]:
            comparison = ScalarValue.model_construct(root=item.system_value()).compare(best.system_value())
            if comparison is None:
                return NativeCollection.model_construct(root=[])
            if (operation == "min" and comparison < 0) or (operation == "max" and comparison > 0):
                best = item
        return NativeCollection.model_construct(root=[best])
