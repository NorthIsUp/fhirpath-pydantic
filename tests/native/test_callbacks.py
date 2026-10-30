"""Typed extension callbacks operate on native resource values."""

import pytest
from fhir.resources.patient import Patient
from pydantic import BaseModel, Field, ValidationError

from fhirpath_pydantic import (
    CustomFunction,
    EvaluationOptions,
    FHIRPathError,
    FunctionCall,
    TraceEvent,
    UnsupportedFeatureError,
    compile,
    evaluate,
)
from fhirpath_pydantic.types import Collection


def test_trace_without_callback_returns_input() -> None:
    """Tracing is a no-op unless the caller explicitly supplies a trace sink."""
    assert evaluate(None, "(1 | 2).trace('values')") == [1, 2]


class CallbackRecorder(BaseModel):
    """Native test callbacks keep their own state on a Pydantic model."""

    events: list[TraceEvent] = Field(default_factory=list[TraceEvent])
    calls: list[FunctionCall] = Field(default_factory=list[FunctionCall])
    multiplier: int = 1

    def trace(self, event: TraceEvent) -> None:
        """Record explicit trace requests without producing console output."""
        self.events.append(event)

    def identity(self, call: FunctionCall) -> Collection:
        """Return the caller's original resource values."""
        self.calls.append(call)
        return call.focus

    def multiply(self, call: FunctionCall) -> Collection:
        """Apply an integer multiplier to the native input collection."""
        self.calls.append(call)
        factor = self.multiplier
        if call.arguments:
            assert len(call.arguments[0]) == 1
            argument = call.arguments[0][0]
            assert isinstance(argument, int)
            factor *= argument
        result: Collection = []
        for value in call.focus:
            assert isinstance(value, int)
            result.append(value * factor)
        return result


def test_trace_preserves_identity_and_projects_values(capsys: pytest.CaptureFixture[str]) -> None:
    """An explicit projection reaches only the chosen trace sink."""
    recorder = CallbackRecorder()
    resource = Patient.model_validate({"active": False})
    options = EvaluationOptions(trace=recorder.trace)
    assert evaluate(resource, "$this.trace('active', active)", options=options)[0] is resource
    assert recorder.events == [TraceEvent(label="active", values=[False])]
    assert capsys.readouterr().out == ""


def test_trace_does_not_evaluate_an_unused_projection() -> None:
    """An unconfigured trace does not evaluate a projection that cannot be observed."""
    assert evaluate(None, "1.trace('unused', %undefined)") == [1]


def test_custom_function_receives_native_models() -> None:
    """Typed callbacks receive native objects and return their original identity."""
    recorder = CallbackRecorder()
    resource = Patient.model_validate({"active": True})
    options = EvaluationOptions(functions=(CustomFunction(name="nativeIdentity", handler=recorder.identity),))
    assert evaluate(resource, "$this.nativeIdentity()", options=options)[0] is resource
    assert recorder.calls[0].focus[0] is resource


def test_custom_function_arguments_are_collections() -> None:
    """Custom functions receive already evaluated, typed collection arguments."""
    recorder = CallbackRecorder()
    options = EvaluationOptions(functions=(CustomFunction(name="multiply", handler=recorder.multiply, arity=(1,)),))
    assert evaluate(None, "(1 | 2).multiply(%factor)", {"factor": 3}, options=options) == [3, 6]
    assert recorder.calls[0].arguments == ([3],)


def test_query_registrations_are_isolated() -> None:
    """Identical expressions may safely use different compiled callback registrations."""
    double, triple = CallbackRecorder(multiplier=2), CallbackRecorder(multiplier=3)
    first = compile(
        "1.multiply()", options=EvaluationOptions(functions=(CustomFunction(name="multiply", handler=double.multiply),))
    )
    second = compile(
        "1.multiply()", options=EvaluationOptions(functions=(CustomFunction(name="multiply", handler=triple.multiply),))
    )
    assert first(None) == [2]
    assert second(None) == [3]
    with pytest.raises(UnsupportedFeatureError):
        evaluate(None, "1.multiply()")


def test_custom_function_can_override_a_builtin() -> None:
    """The upstream extension-table override capability remains available."""
    recorder = CallbackRecorder()
    options = EvaluationOptions(functions=(CustomFunction(name="count", handler=recorder.identity),))
    assert evaluate(None, "(1 | 2).count()", options=options) == [1, 2]


def test_custom_function_arity_is_checked_before_arguments() -> None:
    """Noncontiguous allowed arities reject invalid calls before evaluating data."""
    recorder = CallbackRecorder()
    options = EvaluationOptions(
        functions=(CustomFunction(name="nativeIdentity", handler=recorder.identity, arity=(0, 2)),)
    )
    with pytest.raises(FHIRPathError, match="argument count"):
        evaluate(None, "1.nativeIdentity(%undefined)", options=options)
    assert recorder.calls == []


@pytest.mark.parametrize(
    ("name", "arity"), [("not a function", (0,)), ("valid", ()), ("valid", (-1,)), ("valid", (0, 0))]
)
def test_registration_validation(name: str, arity: tuple[int, ...]) -> None:
    """Function definitions are validated by Pydantic at registration time."""
    recorder = CallbackRecorder()
    with pytest.raises(ValidationError):
        CustomFunction(name=name, handler=recorder.identity, arity=arity)


def test_duplicate_function_names_are_rejected() -> None:
    """A duplicate registration cannot silently overwrite another handler."""
    recorder = CallbackRecorder()
    function = CustomFunction(name="identity", handler=recorder.identity)
    with pytest.raises(ValidationError, match="unique"):
        EvaluationOptions(functions=(function, function))


def test_callback_result_is_validated_at_the_boundary() -> None:
    """Even a foreign callable's wrong return shape is checked before evaluation continues."""
    function = CustomFunction.model_validate({"name": "broken", "handler": str})
    with pytest.raises(ValidationError):
        evaluate(None, "1.broken()", options=EvaluationOptions(functions=(function,)))
