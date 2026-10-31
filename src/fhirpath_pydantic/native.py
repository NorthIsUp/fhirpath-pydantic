"""Pydantic models own FHIR field planning, traversal and result collections."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from functools import cached_property, lru_cache
from typing import Annotated, Self

from fhir.resources.R4B.resource import Resource as R4BResource
from fhir.resources.resource import Resource as R5Resource
from fhir_core.fhirabstractmodel import FHIRAbstractModel
from pydantic import BaseModel, ConfigDict, Field, RootModel, TypeAdapter

from fhirpath_pydantic.decimal_value import DecimalValue
from fhirpath_pydantic.temporal import TemporalValue
from fhirpath_pydantic.type_info import TypeInfo
from fhirpath_pydantic.types import Collection, FHIRPathError, InputValue, NativeModel, Value

_VALUE = TypeAdapter[Value](Value)
type ResourceModel = Annotated[R4BResource, NativeModel] | Annotated[R5Resource, NativeModel]


class NativeInput(RootModel[Value]):
    """Readonly input shapes normalize through Pydantic while native models retain identity."""

    @classmethod
    def from_value(cls, value: InputValue) -> Self:
        """Convert sequences and mappings into internal values without dumping models."""
        return cls.model_validate(value)

    @classmethod
    def variables(cls, bindings: Mapping[str, InputValue]) -> dict[str, Value]:
        """Normalize call-local environment bindings through the same input boundary."""
        return {name: cls.from_value(value).root for name, value in bindings.items()}


class Item(BaseModel):
    """A native value and its optional primitive extension companion."""

    model_config = ConfigDict(frozen=True)
    value: Value = None
    extension: Value = None
    owner: ResourceModel | None = None
    declared_type: TypeInfo | None = None
    temporal: Annotated[TemporalValue, NativeModel] | None = None

    @classmethod
    def singleton(cls, collection: list[Item]) -> Value:
        """Require at most one item and expose its implicit System value."""
        if len(collection) > 1:
            raise FHIRPathError("Expected a singleton collection")
        return collection[0].system_value() if collection else None

    @classmethod
    def boolean(cls, collection: list[Item]) -> bool | None:
        """Evaluate a singleton collection with FHIRPath Boolean semantics."""
        if not collection:
            return None
        value = cls.singleton(collection)
        return value if isinstance(value, bool) else True

    @classmethod
    def integer(cls, collection: list[Item]) -> int:
        """Require one Integer item without Boolean coercion."""
        value = cls.singleton(collection)
        if isinstance(value, bool) or not isinstance(value, int):
            raise FHIRPathError("Expected an Integer singleton")
        return value

    @classmethod
    def string(cls, collection: list[Item]) -> str:
        """Require one String item without implicit numeric conversion."""
        if not isinstance(value := cls.singleton(collection), str):
            raise FHIRPathError("Expected a String singleton")
        return value

    def temporal_value(self) -> TemporalValue | None:
        """Read retained syntax precision or the native field's declared temporal representation."""
        if self.temporal is not None:
            return self.temporal
        if self.declared_type is not None:
            match self.declared_type.name, self.value:
                case (("date" | "dateTime" | "instant"), str()):
                    return TemporalValue.from_text(self.value, "DateTime")
                case "date", date() if not isinstance(self.value, datetime):
                    return TemporalValue(
                        kind="DateTime", year=self.value.year, month=self.value.month, day=self.value.day
                    )
                case "time", str():
                    return TemporalValue.from_text(self.value, "Time")
                case _:
                    pass
        return TemporalValue.from_value(self.value)

    def system_value(self) -> Value:
        """Convert declared FHIR temporal primitives only at an operation boundary."""
        if self.declared_type is not None:
            match self.declared_type.name, self.value:
                case (("date" | "dateTime" | "instant" | "time"), str()) | ("date", date()) if not isinstance(
                    self.value, datetime
                ):
                    temporal = self.temporal_value()
                    assert temporal is not None
                    return temporal.native()
                case _:
                    pass
        return self.value

    def precision(self) -> int | None:
        """Report represented numeric or temporal digits without inventing a missing value."""
        if self.value is None:
            return None
        if (temporal := self.temporal_value()) is not None:
            return temporal.precision()
        match self.value:
            case int() if not isinstance(self.value, bool):
                return 0
            case Decimal() | float():
                return DecimalValue.model_validate(self.value).precision()
            case _:
                raise FHIRPathError("precision() requires a Decimal, Date, DateTime or Time")

    @classmethod
    def from_temporal(cls, temporal: TemporalValue) -> Self:
        """Keep declared precision internally while exposing the corresponding native value."""
        return cls(value=temporal.native(), temporal=temporal)

    def type_info(self) -> TypeInfo:
        """Return declared FHIR identity before inferring the native representation."""
        return self.declared_type if self.declared_type is not None else TypeInfo.from_value(self.value)

    def is_type(self, target: str, *, implicit: bool = False) -> bool:
        """Type tests retain primitive declarations through collection operations."""
        return self.type_info().matches(target, self.value, implicit=implicit)

    @classmethod
    def from_native(
        cls,
        value: Value,
        extension: Value = None,
        owner: ResourceModel | None = None,
        declared_type: TypeInfo | None = None,
    ) -> Self:
        """Retain the enclosing resource needed for local reference resolution."""
        scope = value if isinstance(value, (R4BResource, R5Resource)) else owner
        return cls(value=value, extension=extension, owner=scope, declared_type=declared_type)

    def resource_type(self) -> str | None:
        """Read the resource or datatype name without serialization."""
        if isinstance(self.value, FHIRAbstractModel):
            return self.value.__resource_type__
        if isinstance(self.value, BaseModel):
            return type(self.value).__name__
        if isinstance(self.value, dict) and isinstance(name := self.value.get("resourceType"), str):
            return name
        return None

    def member(self, name: str) -> NativeCollection:
        """Resolve a FHIR alias or choice group against this original value."""
        result: list[Item] = []
        if name in {"extension", "id"} and self.extension is not None:
            result.extend(NativeCollection.from_value(self.extension, owner=self.owner).member(name).root)
        if name == "resourceType":
            result.extend(NativeCollection.from_value(self.resource_type()).root)
        elif name[:1].isupper():
            if self.resource_type() == name:
                result.append(self)
        elif isinstance(self.value, BaseModel):
            for plan in ModelPlan.from_model(type(self.value)).fields.get(name, ()):
                result.extend(plan.read(self.value, owner=self.owner).root)
        elif isinstance(self.value, dict):
            result.extend(
                NativeCollection.from_field(self.value.get(name), self.value.get(f"_{name}"), owner=self.owner).root
            )
        return NativeCollection(root=result)

    def children(self) -> NativeCollection:
        """Return this item's direct FHIR children in model field order."""
        result: list[Item] = []
        if isinstance(self.value, BaseModel):
            for name in ModelPlan.from_model(type(self.value)).children:
                result.extend(self.member(name).root)
        elif isinstance(self.value, dict):
            for name in self.value:
                if name != "resourceType" and not name.startswith("_"):
                    result.extend(self.member(name).root)
        return NativeCollection(root=result)


class FieldMetadata(BaseModel):
    """FHIR annotations relevant to native traversal."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    element_property: bool | None = None
    one_of_many: str | None = None


class FieldPlan(BaseModel):
    """Python attribute behind a FHIR alias or choice group."""

    model_config = ConfigDict(frozen=True)
    name: str
    companion: str | None = None
    declared_type: TypeInfo | None = None

    def read(self, model: BaseModel, *, owner: ResourceModel | None = None) -> NativeCollection:
        """Validate the third-party attribute boundary without dumping models."""
        value = _VALUE.validate_python(vars(model).get(self.name), strict=True)
        companion = (
            _VALUE.validate_python(vars(model).get(self.companion), strict=True) if self.companion is not None else None
        )
        return NativeCollection.from_field(value, companion, owner=owner, declared_type=self.declared_type)


class ModelPlan(BaseModel):
    """Precomputed navigation metadata, never resource instances."""

    model_config = ConfigDict(frozen=True)
    fields: dict[str, tuple[FieldPlan, ...]] = Field(default_factory=dict)
    children: tuple[str, ...] = ()

    @classmethod
    @lru_cache(maxsize=256)
    def from_model(cls, model: type[BaseModel]) -> ModelPlan:
        """Discover aliases and choice groups once per concrete model class."""
        fields: dict[str, tuple[FieldPlan, ...]] = {}
        children: list[str] = []
        for name, field in model.model_fields.items():
            metadata = FieldMetadata.model_validate(field.json_schema_extra or {})
            if metadata.element_property is False and not (
                model.__name__ == "FHIRPrimitiveExtension" and name in {"id", "extension"}
            ):
                continue
            alias = field.alias or name
            companion = f"{name}__ext" if f"{name}__ext" in model.model_fields else None
            plan = FieldPlan(
                name=name,
                companion=companion,
                declared_type=TypeInfo.from_annotation(field.rebuild_annotation(), model=model)
                if issubclass(model, FHIRAbstractModel)
                else None,
            )
            fields[alias] = (plan,)
            if not alias.startswith("_"):
                children.append(alias)
            if metadata.one_of_many is not None:
                fields[metadata.one_of_many] = (*fields.get(metadata.one_of_many, ()), plan)
        return cls(fields=fields, children=tuple(children))


class NativeCollection(RootModel[list[Item]]):
    """An ordered FHIRPath collection retaining native values and extensions."""

    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_value(cls, value: Value, *, owner: ResourceModel | None = None) -> Self:
        """Normalize a known native value without revalidating model instances."""
        if value is None:
            return cls(root=[])
        if isinstance(value, list):
            return cls(root=[Item.from_native(entry, owner=owner) for entry in value if entry is not None])
        return cls(root=[Item.from_native(value, owner=owner)])

    @classmethod
    def from_field(
        cls,
        value: Value,
        companion: Value,
        *,
        owner: ResourceModel | None = None,
        declared_type: TypeInfo | None = None,
    ) -> Self:
        """Align null primitive-array slots with their extension companions."""
        values = value if isinstance(value, list) else [value]
        companions = companion if isinstance(companion, list) else [companion]
        return cls(
            root=[
                Item.from_native(
                    value=values[index] if index < len(values) else None,
                    extension=companions[index] if index < len(companions) else None,
                    owner=owner,
                    declared_type=declared_type,
                )
                for index in range(max(len(values), len(companions)))
                if (index < len(values) and values[index] is not None)
                or (index < len(companions) and companions[index] is not None)
            ]
        )

    @cached_property
    def identities(self) -> dict[int, tuple[Item, ...]]:
        """Index call-local values without conflating equal primitives or their owners."""
        result: dict[int, tuple[Item, ...]] = {}
        for item in self.root:
            key = id(item.value)
            result[key] = (*result.get(key, ()), item)
        return result

    def reframe(self, focus: InputValue, *, index: int | None = None) -> Self:
        """Retain known FHIR metadata when a callback selects its original native elements."""
        selected = type(self).from_value(NativeInput.from_value(focus).root)
        if len(selected.root) == len(self.root) and all(
            current.value is original.value for current, original in zip(selected.root, self.root, strict=True)
        ):
            return self
        if (
            len(selected.root) == 1
            and index is not None
            and 0 <= index < len(self.root)
            and selected.root[0].value is self.root[index].value
        ):
            return type(self)(root=[self.root[index]])
        result: list[Item] = []
        for item in selected.root:
            candidates = self.identities.get(id(item.value), ())
            if len(candidates) > 1:
                raise FHIRPathError("Ambiguous native callback focus; supply its original index")
            result.append(candidates[0] if candidates else item)
        return type(self)(root=result)

    def member(self, name: str) -> Self:
        """Flatten a field selection across every item in this collection."""
        return type(self)(root=[child for item in self.root for child in item.member(name).root])

    def children(self) -> Self:
        """Flatten direct-child collections without serializing native values."""
        return type(self)(root=[child for item in self.root for child in item.children().root])

    def values(self) -> Collection:
        """Unwrap results, preserving original models and native scalar types."""
        return [item.value for item in self.root if item.value is not None]


def items(value: Value) -> list[Item]:
    """Normalize input through the collection model."""
    return NativeCollection.from_value(value).root


def model_plan(model: type[BaseModel]) -> ModelPlan:
    """Return the cached metadata plan owned by ModelPlan."""
    return ModelPlan.from_model(model)


def resource_type(value: Value) -> str | None:
    """Read resource identity through its native item wrapper."""
    return Item.model_construct(value=value).resource_type()


def member(collection: list[Item], name: str) -> list[Item]:
    """Select members through the native collection model."""
    return NativeCollection(root=collection).member(name).root


def children(collection: list[Item]) -> list[Item]:
    """Select children through the native collection model."""
    return NativeCollection(root=collection).children().root


def values(collection: list[Item]) -> Collection:
    """Unwrap values through the native collection model."""
    return NativeCollection(root=collection).values()
