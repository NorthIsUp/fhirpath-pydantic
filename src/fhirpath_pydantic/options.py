"""Validated extension contracts for native FHIRPath evaluation."""

from collections.abc import Callable
from functools import cached_property
from types import EllipsisType
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from fhirpath_pydantic.types import Collection, FHIRPathError, InputValue, Value

_COLLECTION = TypeAdapter[Collection](Collection)
_VALUE = TypeAdapter[Value](Value)
type ArgumentCount = Annotated[int, Field(ge=0, strict=True)]
_ARGUMENT_COUNT = TypeAdapter[ArgumentCount](ArgumentCount)


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


class FunctionArity(BaseModel):
    """Inclusive argument bounds; an absent maximum permits unbounded calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    minimum: ArgumentCount = 0
    maximum: ArgumentCount | None = None

    @model_validator(mode="after")
    def ordered_bounds(self) -> Self:
        """Reject impossible ranges when defining a callback."""
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("Maximum arity cannot be smaller than minimum arity")
        return self

    def accepts(self, count: int) -> bool:
        """Check a runtime argument count against the validated inclusive range."""
        return count >= self.minimum and (self.maximum is None or count <= self.maximum)


class FunctionArgument(BaseModel):
    """A deferred expression bound to one evaluation, without exposing mutable engine state."""

    model_config = ConfigDict(frozen=True)
    name: str
    evaluator: Callable[[InputValue | EllipsisType, int | None], Collection]

    def evaluate(self, focus: InputValue | EllipsisType = ..., *, index: int | None = None) -> Collection:
        """Use the bound FHIR focus by default, or explicitly reframe native values and index."""
        count = None if index is None else _ARGUMENT_COUNT.validate_python(index, strict=True)
        return _COLLECTION.validate_python(self.evaluator(focus, count), strict=True)


class MacroCall(BaseModel):
    """Native focus and independently deferred arguments supplied to a custom macro."""

    model_config = ConfigDict(frozen=True)
    name: str
    focus: Collection
    arguments: tuple[FunctionArgument, ...] = ()


class FunctionDefinition(BaseModel):
    """Shared registration invariants for eager functions and deferred macros."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    arity: tuple[ArgumentCount, ...] | FunctionArity = (0,)

    @field_validator("name")
    @classmethod
    def valid_identifier(cls, name: str) -> str:
        """Function names are identifiers, never interpolated expression text."""
        if not name.isidentifier():
            raise ValueError("A custom function name must be an identifier")
        return name

    @field_validator("arity")
    @classmethod
    def valid_arity(cls, arity: tuple[int, ...] | FunctionArity) -> tuple[int, ...] | FunctionArity:
        """Require at least one unambiguous supported argument count."""
        if isinstance(arity, tuple) and (not arity or len(set(arity)) != len(arity)):
            raise ValueError("Custom function arities must be nonempty and unique")
        return arity

    def check_arity(self, count: int) -> None:
        """Reject invalid calls before evaluating their argument expressions."""
        accepted = self.arity.accepts(count) if isinstance(self.arity, FunctionArity) else count in self.arity
        if not accepted:
            raise FHIRPathError(f"Invalid argument count for {self.name}()")


class CustomFunction(FunctionDefinition):
    """An eager native collection handler with validated argument counts."""

    kind: Literal["function"] = "function"
    handler: Callable[[FunctionCall], Collection]

    def invoke(self, focus: Collection, arguments: tuple[Collection, ...]) -> Collection:
        """Validate the callback's return boundary without dumping native models."""
        self.check_arity(len(arguments))
        call = FunctionCall(name=self.name, focus=focus, arguments=arguments)
        return _COLLECTION.validate_python(self.handler(call), strict=True)


class CustomMacro(FunctionDefinition):
    """A native callback that controls which expressions evaluate and at what focus."""

    kind: Literal["macro"] = "macro"
    handler: Callable[[MacroCall], Collection]

    def invoke(self, focus: Collection, arguments: tuple[FunctionArgument, ...]) -> Collection:
        """Keep arguments deferred and validate the callback's native result."""
        self.check_arity(len(arguments))
        return _COLLECTION.validate_python(
            self.handler(MacroCall(name=self.name, focus=focus, arguments=arguments)), strict=True
        )


class EvaluationOptions(BaseModel):
    """Immutable per-query extension registrations; no implicit I/O is performed."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    functions: tuple[CustomFunction | CustomMacro, ...] = ()
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
    def invocation_table(self) -> dict[str, CustomFunction | CustomMacro]:
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
