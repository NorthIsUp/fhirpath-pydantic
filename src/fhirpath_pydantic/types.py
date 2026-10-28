"""Closed native value types and explicit evaluation errors."""

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

type Scalar = str | bool | int | float | Decimal | date | datetime | time | bytes | UUID
type Value = Scalar | BaseModel | list[Value] | dict[str, Value] | None
type Collection = list[Value]


class FHIRPathError(ValueError):
    """Invalid FHIRPath syntax or semantics."""


class UnsupportedFeatureError(FHIRPathError):
    """A feature outside the native engine's supported subset."""
