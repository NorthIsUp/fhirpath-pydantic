from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, TypedDict

from fhirpath_pydantic.types import Collection, InputValue, Value

class UserInvocation(TypedDict):
    fn: Callable[[list[int], int], list[int]] | Callable[[list[int]], list[int]]
    arity: dict[int, list[str]]

class Options(TypedDict, total=False):
    userInvocationTable: dict[str, UserInvocation]

class Evaluator(Protocol):
    def __call__(self, resource: InputValue, context: Mapping[str, InputValue] | None = None) -> Collection: ...

def compile(path: str, model: Mapping[str, Value] | None = None, options: Options | None = None) -> Evaluator: ...
def evaluate(
    resource: InputValue,
    path: str | Mapping[str, Value],
    context: Mapping[str, InputValue] | None = None,
    model: Mapping[str, Value] | None = None,
    options: Options | None = None,
) -> Collection: ...

class CompiledFirst[I, O](Protocol):
    def __call__(self, resource: I, context: Mapping[str, InputValue] | None = None) -> O | None: ...

class CompiledArray[I, O](Protocol):
    def __call__(self, resource: I, context: Mapping[str, InputValue] | None = None) -> Sequence[O]: ...

def compile_as_first[I, O](expression: str, input_type: type[I], output_type: type[O]) -> CompiledFirst[I, O]: ...
def compile_as_array[I, O](expression: str, input_type: type[I], output_type: type[O]) -> CompiledArray[I, O]: ...
