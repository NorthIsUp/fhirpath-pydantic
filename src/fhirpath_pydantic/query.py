"""Compiled queries and reusable Pydantic result adapters."""

from collections.abc import Mapping
from functools import lru_cache
from typing import Protocol, overload

from pydantic import BaseModel, ConfigDict, TypeAdapter

from fhirpath_pydantic.engine import State, evaluate_node
from fhirpath_pydantic.expressions import Expression
from fhirpath_pydantic.native import items, values
from fhirpath_pydantic.syntax import Node, parse
from fhirpath_pydantic.types import FHIRPathError, Value


class CompiledQuery[T](BaseModel):
    """A reusable syntax tree and result adapter containing no evaluation state."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    node: Node
    adapter: TypeAdapter[T]

    @classmethod
    @lru_cache(maxsize=512)
    def from_text(cls, expression: str, adapter: TypeAdapter[T]) -> CompiledQuery[T]:
        """Cache a validated compiled plan without retaining evaluation inputs."""
        return cls(node=parse(expression), adapter=adapter)

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
        result = values(evaluate_node(self.node, items(resource), State(variables=variables)))
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
def compile(expression: str | Expression, *, output_type: None = None) -> CompiledQuery[Value]: ...
@overload
def compile[T](expression: str | Expression, *, output_type: type[T]) -> CompiledQuery[T]: ...
def compile[T](
    expression: str | Expression, *, output_type: type[T] | None = None
) -> CompiledQuery[T] | CompiledQuery[Value]:
    """Compile syntax once and reuse its Pydantic validator for all evaluations."""
    if isinstance(expression, str) and output_type is None:
        return CompiledQuery[Value].from_text(expression, _VALUE_ADAPTER)
    node = parse(expression) if isinstance(expression, str) else expression.node
    if output_type is None:
        return CompiledQuery[Value](node=node, adapter=TypeAdapter[Value](Value))
    return CompiledQuery[T](node=node, adapter=TypeAdapter[T](output_type))


_VALUE_ADAPTER = TypeAdapter[Value](Value)


def evaluate(resource: Value, expression: str | Expression, context: Mapping[str, Value] | None = None) -> list[Value]:
    """Evaluate FHIRPath on native FHIR resources without dumping them."""
    return compile(expression)(resource, context)


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
    expression: str | Expression, input_type: type[I], output_type: type[O]
) -> CompiledArray[I, O]:
    """Compile a query with checked input and output types."""
    query = compile(expression, output_type=output_type)

    def run(resource: I, context: Mapping[str, Value] | None = None) -> list[O]:
        if not isinstance(resource, input_type):
            raise FHIRPathError(f"Expected input type {input_type.__name__}")
        return query(resource, context)

    return run


def compile_as_first[I: Value, O](
    expression: str | Expression, input_type: type[I], output_type: type[O]
) -> CompiledFirst[I, O]:
    """Compile a typed query returning its first result or None."""
    query = compile_as_array(expression, input_type, output_type)

    def run(resource: I, context: Mapping[str, Value] | None = None) -> O | None:
        result = query(resource, context)
        return result[0] if result else None

    return run
