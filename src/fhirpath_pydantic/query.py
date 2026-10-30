"""Compiled queries and reusable Pydantic result adapters."""

from collections.abc import Mapping
from functools import lru_cache
from typing import Protocol, overload

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from fhirpath_pydantic.engine import State, evaluate_node
from fhirpath_pydantic.expressions import Expression
from fhirpath_pydantic.native import items, values
from fhirpath_pydantic.options import EvaluationOptions
from fhirpath_pydantic.references import ResolutionScope
from fhirpath_pydantic.syntax import Node, parse
from fhirpath_pydantic.types import FHIRPathError, Value


class CompiledQuery[T](BaseModel):
    """A reusable syntax tree and result adapter containing no evaluation state."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    node: Node
    adapter: TypeAdapter[T]
    options: EvaluationOptions = Field(default_factory=EvaluationOptions)

    @classmethod
    @lru_cache(maxsize=512)
    def from_text(cls, expression: str, adapter: TypeAdapter[T]) -> CompiledQuery[T]:
        """Cache a validated compiled plan without retaining evaluation inputs."""
        return cls(node=parse(expression), adapter=adapter)

    @classmethod
    def from_expression(
        cls, expression: str | Expression, adapter: TypeAdapter[T], options: EvaluationOptions | None = None
    ) -> CompiledQuery[T]:
        """Construct a native query, caching only default text-based configurations."""
        if isinstance(expression, str) and options is None:
            return cls.from_text(expression, adapter)
        node = parse(expression) if isinstance(expression, str) else expression.node
        return cls(node=node, adapter=adapter, options=options if options is not None else EvaluationOptions())

    def as_array[I: Value](self, input_type: type[I]) -> CompiledArray[I, T]:
        """Expose a callback that checks the declared native input model."""

        def run(resource: I, context: Mapping[str, Value] | None = None) -> list[T]:
            if not isinstance(resource, input_type):
                raise FHIRPathError(f"Expected input type {input_type.__name__}")
            return self(resource, context)

        return run

    def as_first[I: Value](self, input_type: type[I]) -> CompiledFirst[I, T]:
        """Expose a typed optional-first callback with native input checking."""
        query = self.as_array(input_type)

        def run(resource: I, context: Mapping[str, Value] | None = None) -> T | None:
            result = query(resource, context)
            return result[0] if result else None

        return run

    def __call__(self, resource: Value, context: Mapping[str, Value] | None = None) -> list[T]:
        """Evaluate and strictly validate each returned native value."""
        variables: dict[str, Value] = {
            "resource": resource,
            "rootResource": resource,
            "context": resource,
            "ucum": "http://unitsofmeasure.org",
        }
        if context is not None:
            variables.update(context)
        result = values(
            evaluate_node(
                self.node,
                items(resource),
                State(
                    variables=variables,
                    context_focus=tuple(items(resource)),
                    options=self.options,
                    resolution=ResolutionScope(resource=variables["rootResource"]),
                ),
            )
        )
        return [self.adapter.validate_python(value, strict=True) for value in result]

    def first(self, resource: Value, context: Mapping[str, Value] | None = None) -> T | None:
        """Return the first result or None."""
        result = self(resource, context)
        return result[0] if result else None

    def one(self, resource: Value, context: Mapping[str, Value] | None = None) -> T | None:
        """Return at most one result, rejecting unexpected cardinality."""
        result = self(resource, context)
        if len(result) > 1:
            raise FHIRPathError("Expected a singleton result")
        return result[0] if result else None


@overload
def compile(
    expression: str | Expression, *, output_type: None = None, options: EvaluationOptions | None = None
) -> CompiledQuery[Value]: ...
@overload
def compile[T](
    expression: str | Expression, *, output_type: type[T], options: EvaluationOptions | None = None
) -> CompiledQuery[T]: ...
def compile[T](
    expression: str | Expression, *, output_type: type[T] | None = None, options: EvaluationOptions | None = None
) -> CompiledQuery[T] | CompiledQuery[Value]:
    """Compile syntax once and reuse its Pydantic validator for all evaluations."""
    if output_type is None:
        return CompiledQuery[Value].from_expression(expression, _VALUE_ADAPTER, options)
    return CompiledQuery[T].from_expression(expression, TypeAdapter[T](output_type), options)


_VALUE_ADAPTER = TypeAdapter[Value](Value)


def evaluate(
    resource: Value,
    expression: str | Expression,
    context: Mapping[str, Value] | None = None,
    *,
    options: EvaluationOptions | None = None,
) -> list[Value]:
    """Evaluate FHIRPath on native FHIR resources without dumping them."""
    return compile(expression, options=options)(resource, context)


class CompiledArray[I, O](Protocol):
    """Typed input/output contract for compatibility with fhirpathpy helpers."""

    def __call__(self, resource: I, context: Mapping[str, Value] | None = None) -> list[O]:
        """Evaluate a resource and return all validated results."""
        ...


class CompiledFirst[I, O](Protocol):
    """Typed optional-singleton contract for compatibility helpers."""

    def __call__(self, resource: I, context: Mapping[str, Value] | None = None) -> O | None:
        """Evaluate a resource and return its first validated result."""
        ...


def compile_as_array[I: Value, O](
    expression: str | Expression, input_type: type[I], output_type: type[O], *, options: EvaluationOptions | None = None
) -> CompiledArray[I, O]:
    """Compile a query with checked input and output types."""
    return compile(expression, output_type=output_type, options=options).as_array(input_type)


def compile_as_first[I: Value, O](
    expression: str | Expression, input_type: type[I], output_type: type[O], *, options: EvaluationOptions | None = None
) -> CompiledFirst[I, O]:
    """Compile a typed query returning its first result or None."""
    return compile(expression, output_type=output_type, options=options).as_first(input_type)
