"""Declared FHIR types and native System types share explicit metadata."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import ClassVar, Self, get_args
from uuid import UUID

from fhir_core.constraints import FHIR_PRIMITIVES_MAPS
from fhir_core.fhirabstractmodel import FHIRAbstractModel
from pydantic import BaseModel, ConfigDict

from fhirpath_pydantic.quantities import QuantityValue
from fhirpath_pydantic.temporal import TemporalValue
from fhirpath_pydantic.types import Value


class TypeInfo(BaseModel):
    """FHIRPath type metadata retains namespace and declared primitive identity."""

    model_config = ConfigDict(frozen=True)
    namespace: str
    name: str

    PRIMITIVES: ClassVar[dict[str, str]] = {
        "boolean": "Boolean",
        "integer": "Integer",
        "unsignedInt": "Integer",
        "positiveInt": "Integer",
        "integer64": "Long",
        "decimal": "Decimal",
        "string": "String",
        "code": "String",
        "uri": "String",
        "url": "String",
        "canonical": "String",
        "id": "String",
        "oid": "String",
        "uuid": "String",
        "markdown": "String",
        "base64Binary": "String",
        "xhtml": "String",
        "date": "DateTime",
        "dateTime": "DateTime",
        "instant": "DateTime",
        "time": "Time",
    }

    @classmethod
    def from_annotation(cls, annotation: object) -> Self | None:
        """Read vendor primitive metadata through optional, list and Annotated types."""
        if isinstance(annotation, type) and (name := FHIR_PRIMITIVES_MAPS.get(annotation)) is not None:
            return cls(namespace="FHIR", name=name)
        arguments: tuple[object, ...] = get_args(annotation)
        # Metadata takes precedence over an Annotated value's underlying Python type.
        for argument in reversed(arguments):
            if (name := FHIR_PRIMITIVES_MAPS.get(type(argument))) is not None:
                return cls(namespace="FHIR", name=name)
        for argument in arguments:
            if (declared := cls.from_annotation(argument)) is not None:
                return declared
        return None

    @classmethod
    def from_value(cls, value: Value) -> Self:
        """Infer a System type only when no declared FHIR field type is available."""
        match value:
            case FHIRAbstractModel():
                return cls(namespace="FHIR", name=value.__resource_type__)
            case QuantityValue():
                name = "Quantity"
            case TemporalValue():
                name = value.kind
            case bool():
                name = "Boolean"
            case int():
                name = "Integer"
            case float() | Decimal():
                name = "Decimal"
            case str() | bytes() | UUID():
                name = "String"
            case datetime():
                name = "DateTime"
            case date():
                name = "Date"
            case time():
                name = "Time"
            case BaseModel():
                return cls(namespace="Python", name=type(value).__name__)
            case dict():
                if isinstance(resource := value.get("resourceType"), str):
                    return cls(namespace="FHIR", name=resource)
                name = "Object"
            case _:
                name = "Object"
        return cls(namespace="System", name=name)

    def matches(self, target: str, value: Value, *, implicit: bool = False) -> bool:
        """Filter types with optional System coercion; is() preserves FHIR identity."""
        namespace, separator, name = target.partition(".")
        if not separator:
            name = namespace
            if self.namespace == "System" and name in {
                "boolean",
                "integer",
                "decimal",
                "string",
                "date",
                "dateTime",
                "time",
            }:
                return self.name == self.PRIMITIVES[name]
            namespace = (
                "FHIR"
                if name in self.PRIMITIVES
                else "System"
                if name in {*self.PRIMITIVES.values(), "Date", "Object", "object"}
                else self.namespace
            )
        if namespace == "System":
            system_name = self.PRIMITIVES.get(self.name) if implicit and self.namespace == "FHIR" else None
            return (self.namespace == "System" and self.name.casefold() == name.casefold()) or (
                system_name is not None and system_name.casefold() == name.casefold()
            )
        if namespace != self.namespace:
            return False
        if self.name == name:
            return True
        if self.namespace == "FHIR" and self.name in self.PRIMITIVES:
            return name in {"Element", "Base"}
        if isinstance(value, BaseModel):
            return any(base.__name__ == name for base in type(value).__mro__)
        return False
