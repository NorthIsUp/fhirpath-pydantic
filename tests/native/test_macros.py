"""Typed custom callbacks retain lazy, scoped and variadic baseline capabilities."""

from concurrent.futures import ThreadPoolExecutor
from types import EllipsisType

import pytest
from fhir.resources.patient import Patient
from pydantic import BaseModel, Field, RootModel, StrictBool, StrictInt, ValidationError
from test_inputs import GuardedPatient

from fhirpath_pydantic import (
    CustomFunction,
    CustomMacro,
    EvaluationOptions,
    FHIRPathError,
    FunctionArgument,
    FunctionArity,
    FunctionCall,
    MacroCall,
    compile,
    evaluate,
    literal,
    path,
    var,
)
from fhirpath_pydantic.types import Collection, InputValue


class Condition(RootModel[tuple[StrictBool]]):
    """The macro's condition boundary requires exactly one actual Boolean."""


class Integers(RootModel[list[StrictInt]]):
    """Variadic argument values use Pydantic validation rather than scalar coercion."""


class Callbacks(BaseModel):
    """Caller-owned native macro behavior and observable invocation counts."""

    calls: list[str] = Field(default_factory=list[str])

    def choose(self, call: MacroCall) -> Collection:
        """Evaluate a condition and only its selected branch."""
        self.calls.append(call.name)
        condition = Condition.model_validate(call.arguments[0].evaluate()).root[0]
        return call.arguments[1 if condition else 2].evaluate()

    def select_where(self, call: MacroCall) -> Collection:
        """Evaluate a predicate at each native element's focus and index."""
        result: Collection = []
        for index, value in enumerate(call.focus):
            condition = Condition.model_validate(call.arguments[0].evaluate([value], index=index)).root[0]
            if condition:
                result.append(value)
        return result

    def first_present(self, call: MacroCall) -> Collection:
        """Choose the first populated deferred argument without a fixed arity limit."""
        for argument in call.arguments:
            if result := argument.evaluate():
                return result
        return []

    def total(self, call: FunctionCall) -> Collection:
        """Sum validated variadic integer values from an eager callback."""
        values = Integers.model_validate([value for argument in call.arguments for value in argument]).root
        return [sum(values)]

    def present_only(self, call: MacroCall) -> Collection:
        """Skip all expression evaluation when there are no underlying native input values."""
        return call.arguments[0].evaluate() if call.focus else []

    def ambiguous_focus(self, call: MacroCall) -> Collection:
        """Request a scalar subset without enough provenance to select a duplicate."""
        return call.arguments[0].evaluate([call.focus[0]])

    def empty_focus(self, call: MacroCall) -> Collection:
        """Explicit None is an empty input, distinct from an omitted bound focus."""
        return call.arguments[0].evaluate(None)

    def argument_index(self, focus: InputValue | EllipsisType, index: int | None) -> Collection:
        """Expose a deferred argument index for its public boundary test."""
        return [index]

    def argument_name(self, call: MacroCall) -> Collection:
        """Read an identifier or type argument without evaluating it as a resource path."""
        return [call.arguments[0].name]


@pytest.fixture
def callbacks() -> Callbacks:
    """Keep callback observations local to each test."""
    return Callbacks()


def test_native_macro_short_circuits_and_preserves_identity(callbacks: Callbacks) -> None:
    """An unselected undefined variable must never evaluate."""
    patient = Patient.model_validate({"active": True, "name": [{"given": ["native"]}]})
    options = EvaluationOptions(functions=(CustomMacro(name="choose", handler=callbacks.choose, arity=(3,)),))
    assert patient.name is not None
    assert evaluate(patient, "choose(active, name.first(), %undefined)", options=options)[0] is patient.name[0]
    assert evaluate(None, "choose(false, %undefined, 42)", options=options) == [42]
    assert callbacks.calls == ["choose", "choose"]
    with pytest.raises(ValidationError):
        evaluate(None, "choose(1, 2, 3)", options=options)


def test_macro_focus_index_and_context_are_call_local(callbacks: Callbacks) -> None:
    """Reused compiled macros isolate the predicate's focus, index and variable bindings."""
    patient = Patient.model_validate({"name": [{"use": "usual", "given": ["a"]}, {"use": "official", "given": ["b"]}]})
    options = EvaluationOptions(
        functions=(CustomMacro(name="nativeWhere", handler=callbacks.select_where, arity=(1,)),)
    )
    query = compile("name.nativeWhere(use = %use and $index = %index).given", output_type=str, options=options)
    assert query(patient, {"use": "official", "index": 1}) == ["b"]
    assert query(patient, {"use": "official", "index": 0}) == []

    def run(index: int) -> list[str]:
        return query(patient, {"use": "official", "index": index})

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, [0, 1] * 4))
    assert results == [[], ["b"]] * 4
    assert patient.name is not None
    assert evaluate(patient, "name.nativeWhere($index = 1)", options=options)[0] is patient.name[1]


def test_variadic_eager_callback_has_validated_bounds(callbacks: Callbacks) -> None:
    """Closed ranges reject wrong arities before touching undefined arguments."""
    options = EvaluationOptions(
        functions=(CustomFunction(name="total", handler=callbacks.total, arity=FunctionArity(minimum=1, maximum=3)),)
    )
    assert evaluate(None, "total(1, 2, 3)", options=options) == [6]
    for expression in ("total()", "total(1, 2, 3, %undefined)"):
        with pytest.raises(FHIRPathError, match="Invalid argument count"):
            evaluate(None, expression, options=options)
    with pytest.raises(ValidationError):
        evaluate(None, "total(true)", options=options)


def test_unbounded_macro_and_eager_calls_need_no_interpolation(callbacks: Callbacks) -> None:
    """Unbounded registrations accept large native AST argument lists and stay lazy."""
    options = EvaluationOptions(
        functions=(
            CustomMacro(name="firstPresent", handler=callbacks.first_present, arity=FunctionArity(minimum=1)),
            CustomFunction(name="total", handler=callbacks.total, arity=FunctionArity()),
        )
    )
    expression = path().call("firstPresent", *(literal([]) for _ in range(100)), literal(42), var("undefined"))
    assert evaluate(None, expression, options=options) == [42]
    assert evaluate(None, path().call("total", *(literal(value) for value in range(101))), options=options) == [5050]
    assert evaluate(None, "total()", options=options) == [0]


def test_macro_wrong_arity_precedes_argument_evaluation(callbacks: Callbacks) -> None:
    """Both fixed and ranged macro registrations validate before invoking the handler."""
    for arity in ((3,), FunctionArity(minimum=3, maximum=3)):
        options = EvaluationOptions(functions=(CustomMacro(name="choose", handler=callbacks.choose, arity=arity),))
        with pytest.raises(FHIRPathError, match="Invalid argument count"):
            evaluate(None, "choose(%undefined)", options=options)
    assert callbacks.calls == []


def test_macro_identifier_arguments_remain_native_data(callbacks: Callbacks) -> None:
    """Parsed and fluent names can be inspected without resource lookup or interpolation."""
    options = EvaluationOptions(
        functions=(CustomMacro(name="argumentName", handler=callbacks.argument_name, arity=(1,)),)
    )
    assert evaluate(None, "argumentName(FHIR.Patient)", options=options) == ["FHIR.Patient"]
    assert evaluate(None, path().call("argumentName", path("name", "given")), options=options) == ["name.given"]


@pytest.mark.parametrize("bounds", [{"minimum": -1}, {"minimum": True}, {"minimum": 2, "maximum": 1}])
def test_invalid_arity_ranges_are_rejected(bounds: dict[str, int | bool]) -> None:
    """Pydantic enforces nonnegative strict counts and ordered bounds."""
    with pytest.raises(ValidationError):
        FunctionArity.model_validate(bounds)


def test_macro_and_eager_names_share_one_registration_namespace(callbacks: Callbacks) -> None:
    """Mixed callback kinds cannot silently shadow each other."""
    with pytest.raises(ValidationError, match="unique"):
        EvaluationOptions(
            functions=(
                CustomMacro(name="same", handler=callbacks.choose, arity=(3,)),
                CustomFunction(name="same", handler=callbacks.total, arity=(0,)),
            )
        )


def test_macro_resource_profiles_are_not_revalidated(callbacks: Callbacks) -> None:
    """Deferred native focus and results preserve instance identity and caller validators."""
    patient = GuardedPatient.model_validate({"active": True})
    before = GuardedPatient.validations
    options = EvaluationOptions(functions=(CustomMacro(name="choose", handler=callbacks.choose, arity=(3,)),))
    assert evaluate(patient, "choose(true, $this, %undefined)", options=options)[0] is patient
    assert GuardedPatient.validations == before


def test_macro_kind_selects_the_correct_pydantic_registration(callbacks: Callbacks) -> None:
    """External registration definitions use an explicit kind to distinguish deferred handlers."""
    options = EvaluationOptions.model_validate(
        {
            "functions": [
                {
                    "kind": "macro",
                    "name": "choose",
                    "handler": callbacks.choose,
                    "arity": [3],
                }
            ]
        }
    )
    assert isinstance(options.functions[0], CustomMacro)
    assert evaluate(None, "choose(false, %undefined, 42)", options=options) == [42]


def test_deferred_argument_indices_are_strict_nonnegative_counts(callbacks: Callbacks) -> None:
    """An explicit public argument focus cannot introduce an invalid FHIRPath index."""
    argument = FunctionArgument(name="index", evaluator=callbacks.argument_index)
    assert argument.evaluate(None, index=2) == [2]
    for index in (-1, True):
        with pytest.raises(ValidationError):
            argument.evaluate(None, index=index)


def test_macro_arguments_inherit_outer_index_and_aggregate_total(callbacks: Callbacks) -> None:
    """Omitting a custom focus index must preserve the surrounding scoped expression."""
    options = EvaluationOptions(functions=(CustomMacro(name="choose", handler=callbacks.choose, arity=(3,)),))
    assert evaluate(None, "(10 | 20).select(choose(true, $index, %undefined))", options=options) == [0, 1]
    assert evaluate(None, "(1 | 2 | 3).aggregate(choose(true, $total + $this, %undefined), 0)", options=options) == [6]


def test_deferred_arguments_keep_declared_primitive_metadata(callbacks: Callbacks) -> None:
    """A bound primitive remains FHIR.code while the macro evaluates its arguments."""
    options = EvaluationOptions(functions=(CustomMacro(name="choose", handler=callbacks.choose, arity=(3,)),))
    patient = Patient.model_validate({"gender": "female"})
    assert evaluate(patient, "gender.choose(true, is(FHIR.code), %undefined)", options=options) == [True]


def test_deferred_arguments_keep_absent_primitive_extensions(callbacks: Callbacks) -> None:
    """An extension-only primitive is still a real bound context even without a scalar value."""
    options = EvaluationOptions(functions=(CustomMacro(name="choose", handler=callbacks.choose, arity=(3,)),))
    patient = Patient.model_validate({"_active": {"extension": [{"url": "test", "valueString": "absent"}]}})
    assert evaluate(patient, "active.choose(true, extension('test').value, %undefined)", options=options) == ["absent"]


def test_deferred_arguments_keep_contained_reference_scope(callbacks: Callbacks) -> None:
    """A native Reference keeps its owning resource while the macro evaluates resolve()."""
    options = EvaluationOptions(functions=(CustomMacro(name="choose", handler=callbacks.choose, arity=(3,)),))
    patient = Patient.model_validate(
        {
            "contained": [{"resourceType": "Organization", "id": "org", "name": "local"}],
            "managingOrganization": {"reference": "#org"},
        }
    )
    assert evaluate(patient, "managingOrganization.choose(true, resolve().name, %undefined)", options=options) == [
        "local"
    ]


def test_indexed_macro_focus_keeps_duplicate_primitive_companions(callbacks: Callbacks) -> None:
    """Identical scalar objects retain their own companion metadata when indexed explicitly."""
    patient = Patient.model_validate(
        {"name": [{"given": ["same", "same"], "_given": [{"id": "first"}, {"id": "second"}]}]}
    )
    assert patient.name is not None and patient.name[0].given is not None
    assert patient.name[0].given[0] is patient.name[0].given[1]
    options = EvaluationOptions(
        functions=(
            CustomMacro(name="nativeWhere", handler=callbacks.select_where, arity=(1,)),
            CustomMacro(name="ambiguousFocus", handler=callbacks.ambiguous_focus, arity=(1,)),
        )
    )
    assert evaluate(patient, "name.given.nativeWhere(id = 'second').count()", options=options) == [1]
    with pytest.raises(FHIRPathError, match="Ambiguous native callback focus"):
        evaluate(patient, "name.given.ambiguousFocus(id)", options=options)


def test_explicit_empty_macro_focus_differs_from_bound_focus(callbacks: Callbacks) -> None:
    """A caller can deliberately evaluate against no resource instead of inheriting the receiver."""
    options = EvaluationOptions(functions=(CustomMacro(name="emptyFocus", handler=callbacks.empty_focus, arity=(1,)),))
    patient = Patient.model_validate({"active": True})
    assert evaluate(patient, "emptyFocus(active)", options=options) == []


def test_custom_scalar_results_are_system_values(callbacks: Callbacks) -> None:
    """Callbacks return native values; result scalars do not guess a field's declared provenance."""
    options = EvaluationOptions(functions=(CustomMacro(name="choose", handler=callbacks.choose, arity=(3,)),))
    patient = Patient.model_validate({"gender": "female"})
    assert evaluate(patient, "choose(true, gender, %undefined).is(System.String)", options=options) == [True]


def test_nullable_input_macro_can_skip_all_arguments(callbacks: Callbacks) -> None:
    """A callback owns its empty-input policy without evaluating an unused argument."""
    options = EvaluationOptions(functions=(CustomMacro(name="ifPresent", handler=callbacks.present_only, arity=(1,)),))
    assert evaluate(None, "{}.ifPresent(%undefined)", options=options) == []
    assert evaluate(None, "42.ifPresent($this + 1)", options=options) == [43]


def test_callback_registration_rejects_unknown_metadata(callbacks: Callbacks) -> None:
    """A misspelled or legacy option must not silently disappear at the native boundary."""
    with pytest.raises(ValidationError, match="Extra inputs"):
        CustomMacro.model_validate({"name": "choose", "handler": callbacks.choose, "variadic": True})
    with pytest.raises(ValidationError, match="Extra inputs"):
        EvaluationOptions.model_validate({"function": []})
