"""Read Pydantic fields directly, retaining aliases, choices and extensions."""

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from fhirpath_pydantic.types import Collection, Value

_VALUE = TypeAdapter[Value](Value)


class Item(BaseModel):
    """A native value and its optional primitive extension companion."""

    model_config = ConfigDict(frozen=True)
    value: Value = None
    extension: Value = None


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


class ModelPlan(BaseModel):
    """Precomputed navigation metadata, never resource instances."""

    fields: dict[str, tuple[FieldPlan, ...]] = Field(default_factory=dict)
    children: tuple[str, ...] = ()


def items(value: Value) -> list[Item]:
    """Normalize an input into a FHIRPath collection."""
    if value is None:
        return []
    if isinstance(value, list):
        return [Item.model_construct(value=entry) for entry in value if entry is not None]
    return [Item.model_construct(value=value)]


@lru_cache(maxsize=256)
def model_plan(model: type[BaseModel]) -> ModelPlan:
    """Discover FHIR aliases and choice groups once per model class."""
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
        plan = FieldPlan(name=name, companion=companion)
        fields[alias] = (plan,)
        if not alias.startswith("_"):
            children.append(alias)
        if metadata.one_of_many is not None:
            fields[metadata.one_of_many] = (*fields.get(metadata.one_of_many, ()), plan)
    return ModelPlan(fields=fields, children=tuple(children))


def _read(model: BaseModel, name: str) -> Value:
    # Validate the untyped third-party attribute boundary without serializing it.
    return _VALUE.validate_python(vars(model).get(name), strict=True)


def _pair(value: Value, companion: Value) -> list[Item]:
    values = value if isinstance(value, list) else [value]
    companions = companion if isinstance(companion, list) else [companion]
    return [
        Item.model_construct(
            value=values[index] if index < len(values) else None,
            extension=companions[index] if index < len(companions) else None,
        )
        for index in range(max(len(values), len(companions)))
        if (index < len(values) and values[index] is not None)
        or (index < len(companions) and companions[index] is not None)
    ]


def resource_type(value: Value) -> str | None:
    """Get the FHIR resource or datatype name without serialization."""
    if isinstance(value, BaseModel):
        return type(value).__name__
    if isinstance(value, dict) and isinstance(name := value.get("resourceType"), str):
        return name
    return None


def member(collection: list[Item], name: str) -> list[Item]:
    """Resolve FHIR aliases and choice fields against original model instances."""
    result: list[Item] = []
    for item in collection:
        value = item.value
        if name == "extension" and item.extension is not None:
            result.extend(member(items(item.extension), "extension"))
        if name == "resourceType":
            result.extend(items(resource_type(value)))
        elif name[:1].isupper():
            if resource_type(value) == name:
                result.append(item)
        elif isinstance(value, BaseModel):
            for plan in model_plan(type(value)).fields.get(name, ()):
                result.extend(
                    _pair(_read(value, plan.name), _read(value, plan.companion) if plan.companion is not None else None)
                )
        elif isinstance(value, dict):
            result.extend(_pair(value.get(name), value.get(f"_{name}")))
    return result


def children(collection: list[Item]) -> list[Item]:
    """Return direct FHIR children in field order."""
    result: list[Item] = []
    for item in collection:
        if isinstance(value := item.value, BaseModel):
            for name in model_plan(type(value)).children:
                result.extend(member([item], name))
        elif isinstance(value, dict):
            for key in value:
                if key != "resourceType" and not key.startswith("_"):
                    result.extend(member([item], key))
    return result


def values(collection: list[Item]) -> Collection:
    """Unwrap results while preserving original models and scalar types."""
    return [item.value for item in collection if item.value is not None]
