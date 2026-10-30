"""Pydantic models own FHIR field planning, traversal and result collections."""

from datetime import date, datetime
from functools import lru_cache
from typing import Self

from fhir.resources.R4B.resource import Resource as R4BResource
from fhir.resources.resource import Resource as R5Resource
from fhir_core.fhirabstractmodel import FHIRAbstractModel
from pydantic import BaseModel, ConfigDict, Field, RootModel, TypeAdapter

from fhirpath_pydantic.temporal import TemporalValue
from fhirpath_pydantic.type_info import TypeInfo
from fhirpath_pydantic.types import Collection, FHIRPathError, Value

_VALUE = TypeAdapter[Value](Value)
type ResourceModel = R4BResource | R5Resource


class Item(BaseModel):
    """A native value and its optional primitive extension companion."""

    model_config = ConfigDict(frozen=True)
    value: Value = None
    extension: Value = None
    owner: ResourceModel | None = None
    declared_type: TypeInfo | None = None

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

    def system_value(self) -> Value:
        """Convert declared FHIR temporal primitives only at an operation boundary."""
        if self.declared_type is not None:
            match self.declared_type.name, self.value:
                case (("date" | "dateTime" | "instant"), str()):
                    return TemporalValue.from_text(self.value, "DateTime").native()
                case "date", date() if not isinstance(self.value, datetime):
                    return TemporalValue(
                        kind="DateTime", year=self.value.year, month=self.value.month, day=self.value.day
                    )
                case "time", str():
                    return TemporalValue.from_text(self.value, "Time").native()
                case _:
                    pass
        return self.value

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
        return cls.model_construct(value=value, extension=extension, owner=scope, declared_type=declared_type)

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
        return NativeCollection.model_construct(root=result)

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
        return NativeCollection.model_construct(root=result)


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
                declared_type=TypeInfo.from_annotation(field.rebuild_annotation())
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
            return cls.model_construct(root=[])
        if isinstance(value, list):
            return cls.model_construct(
                root=[Item.from_native(entry, owner=owner) for entry in value if entry is not None]
            )
        return cls.model_construct(root=[Item.from_native(value, owner=owner)])

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
        return cls.model_construct(
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

    def member(self, name: str) -> Self:
        """Flatten a field selection across every item in this collection."""
        return self.model_construct(root=[child for item in self.root for child in item.member(name).root])

    def children(self) -> Self:
        """Flatten direct-child collections without serializing native values."""
        return self.model_construct(root=[child for item in self.root for child in item.children().root])

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
    return NativeCollection.model_construct(root=collection).member(name).root


def children(collection: list[Item]) -> list[Item]:
    """Select children through the native collection model."""
    return NativeCollection.model_construct(root=collection).children().root


def values(collection: list[Item]) -> Collection:
    """Unwrap values through the native collection model."""
    return NativeCollection.model_construct(root=collection).values()
