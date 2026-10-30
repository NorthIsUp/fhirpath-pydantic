"""Closed native value types and explicit evaluation errors."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema


class NativeModel:
    """Pydantic metadata accepts existing models without JSON or collection coercion."""

    @classmethod
    def __get_pydantic_core_schema__(cls, _source: object, _handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        """Check native identity directly and serialize through the concrete model."""
        return core_schema.is_instance_schema(BaseModel)

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _schema: core_schema.CoreSchema, _handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        """Native models have object-shaped wire values, never generic model inputs."""
        return {"type": "object"}


type Scalar = str | bool | int | float | Decimal | date | datetime | time | bytes | UUID
type Value = Scalar | Annotated[BaseModel, NativeModel] | list[Value] | dict[str, Value] | None
type Collection = list[Value]


class FHIRPathError(ValueError):
    """Invalid FHIRPath syntax or semantics."""


class UnsupportedFeatureError(FHIRPathError):
    """A feature outside the native engine's supported subset."""
