"""Validated extension contracts for native FHIRPath evaluation."""

from collections.abc import Callable
from functools import cached_property
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from fhirpath_pydantic.types import Collection, FHIRPathError, Value

_COLLECTION = TypeAdapter[Collection](Collection)
_VALUE = TypeAdapter[Value](Value)
type ArgumentCount = Annotated[int, Field(ge=0, strict=True)]


class TraceEvent(BaseModel):
    """An explicitly requested trace containing native projected values."""

    model_config = ConfigDict(frozen=True)
    label: str
    values: Collection


class FunctionCall(BaseModel):
    """The typed collection arguments supplied to a registered function."""

    model_config = ConfigDict(frozen=True)
    name: str
    focus: Collection
    arguments: tuple[Collection, ...] = ()


class CustomFunction(BaseModel):
    """A native collection handler with a validated name and allowed arities."""

    model_config = ConfigDict(frozen=True)
    name: str
    handler: Callable[[FunctionCall], Collection]
    arity: tuple[ArgumentCount, ...] = (0,)

    @field_validator("name")
    @classmethod
    def valid_identifier(cls, name: str) -> str:
        """Function names are identifiers, never interpolated expression text."""
        if not name.isidentifier():
            raise ValueError("A custom function name must be an identifier")
        return name

    @field_validator("arity")
    @classmethod
    def valid_arity(cls, arity: tuple[int, ...]) -> tuple[int, ...]:
        """Require at least one unambiguous supported argument count."""
        if not arity or len(set(arity)) != len(arity):
            raise ValueError("Custom function arities must be nonempty and unique")
        return arity

    def check_arity(self, count: int) -> None:
        """Reject invalid calls before evaluating their argument expressions."""
        if count not in self.arity:
            raise FHIRPathError(f"Invalid argument count for {self.name}()")

    def invoke(self, focus: Collection, arguments: tuple[Collection, ...]) -> Collection:
        """Validate the callback's return boundary without dumping native models."""
        self.check_arity(len(arguments))
        call = FunctionCall(name=self.name, focus=focus, arguments=arguments)
        return _COLLECTION.validate_python(self.handler(call), strict=True)


class EvaluationOptions(BaseModel):
    """Immutable per-query extension registrations; no implicit I/O is performed."""

    model_config = ConfigDict(frozen=True)
    functions: tuple[CustomFunction, ...] = ()
    trace: Callable[[TraceEvent], None] | None = None
    resolver: Callable[[str], BaseModel | None] | None = None

    @model_validator(mode="after")
    def unique_function_names(self) -> Self:
        """A query must not silently discard a duplicate registration."""
        names = [function.name for function in self.functions]
        if len(names) != len(set(names)):
            raise ValueError("Custom function names must be unique")
        return self

    @cached_property
    def invocation_table(self) -> dict[str, CustomFunction]:
        """Cache registration metadata, never inputs from an evaluation."""
        return {function.name: function for function in self.functions}

    def resolve(self, reference: str) -> BaseModel | None:
        """Use only the caller-supplied resolver, requiring a native model result."""
        if self.resolver is None:
            return None
        result = _VALUE.validate_python(self.resolver(reference), strict=True)
        if result is not None and not isinstance(result, BaseModel):
            raise FHIRPathError("Reference resolvers must return a Pydantic model or None")
        return result
