"""The native fluent surface covers operators and type tests without parsing text."""

from decimal import Decimal
from importlib.resources import files

import pytest
from fhir.resources.patient import Patient
from pydantic import BaseModel, TypeAdapter, create_model
from test_registry import BaselineRegistry

from fhirpath_pydantic import BinaryOperator, FHIRPathError, evaluate, literal, path, query
from fhirpath_pydantic.types import Collection, Value


class OperatorSchema(BaseModel):
    """Only the enum shape is needed from the public operator JSON schema."""

    enum: frozenset[str]


class OperatorProbe(BaseModel):
    """One independently specified native binary operation."""

    operator: BinaryOperator
    left: Value
    right: Value
    expected: Collection


PROBES = (
    OperatorProbe(operator="|", left=1, right=2, expected=[1, 2]),
    OperatorProbe(operator="=", left=1, right=1, expected=[True]),
    OperatorProbe(operator="!=", left=1, right=2, expected=[True]),
    OperatorProbe(operator="~", left="ABC", right="abc", expected=[True]),
    OperatorProbe(operator="!~", left="ABC", right="xyz", expected=[True]),
    OperatorProbe(operator="<", left=1, right=2, expected=[True]),
    OperatorProbe(operator="<=", left=2, right=2, expected=[True]),
    OperatorProbe(operator=">", left=2, right=1, expected=[True]),
    OperatorProbe(operator=">=", left=2, right=2, expected=[True]),
    OperatorProbe(operator="in", left=1, right=[1, 2], expected=[True]),
    OperatorProbe(operator="contains", left=[1, 2], right=2, expected=[True]),
    OperatorProbe(operator="&", left="a", right="b", expected=["ab"]),
    OperatorProbe(operator="+", left=2, right=3, expected=[5]),
    OperatorProbe(operator="-", left=5, right=2, expected=[3]),
    OperatorProbe(operator="*", left=2, right=3, expected=[6]),
    OperatorProbe(operator="/", left=3, right=2, expected=[Decimal("1.5")]),
    OperatorProbe(operator="mod", left=7, right=3, expected=[1]),
    OperatorProbe(operator="div", left=7, right=3, expected=[2]),
    OperatorProbe(operator="or", left=False, right=True, expected=[True]),
    OperatorProbe(operator="and", left=True, right=False, expected=[False]),
    OperatorProbe(operator="xor", left=True, right=False, expected=[True]),
    OperatorProbe(operator="implies", left=True, right=False, expected=[False]),
)


@pytest.mark.parametrize("probe", PROBES, ids=[probe.operator for probe in PROBES])
def test_every_fluent_binary_operator(probe: OperatorProbe, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every advertised operator evaluates native nodes with the text parser disabled."""

    def reject(expression: str) -> None:
        raise AssertionError("Fluent operations must not parse expression text")

    monkeypatch.setattr(query, "parse", reject)
    assert evaluate(None, literal(probe.left).binary(probe.operator, literal(probe.right))) == probe.expected


def test_operator_probes_cover_the_entire_baseline_surface() -> None:
    """No operator alias or advertised fluent token can be omitted from verification."""
    advertised = OperatorSchema.model_validate(TypeAdapter[BinaryOperator](BinaryOperator).json_schema()).enum
    assert frozenset(probe.operator for probe in PROBES) == advertised
    registry = BaselineRegistry.from_source(files("fhirpathpy.engine.invocations").joinpath("__init__.py").read_text())
    aliases = {"containsOp": "contains", "inOp": "in", "isOp": "is", "asOp": "as"}
    baseline = frozenset(aliases.get(name, name) for name in registry.root - registry.functions())
    assert baseline == advertised | {"is", "as"}


def test_fluent_type_tests_accept_native_models_and_type_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Native type arguments require neither query interpolation nor access to private AST details."""

    def reject(expression: str) -> None:
        raise AssertionError("Fluent type arguments must not parse text")

    monkeypatch.setattr(query, "parse", reject)
    patient = Patient.model_validate({"gender": "female"})
    assert evaluate(patient, path().is_type(Patient)) == [True]
    assert evaluate(patient, path().as_type(Patient))[0] is patient
    assert evaluate(patient, path("gender").is_type("FHIR.string")) == [True]
    assert evaluate(patient, path("gender").as_type("FHIR.string")) == ["female"]
    assert evaluate(patient, path("gender").of_type("FHIR.string")) == ["female"]
    other = create_model("Patient", active=(bool, True))
    assert evaluate(patient, path().is_type(other)) == [False]
    assert evaluate(patient, path().as_type(other)) == []
    assert evaluate(None, literal([]).is_type(Patient)) == []
    assert evaluate(None, literal([]).as_type(Patient)) == []
    for expression in (path().is_type(Patient), path().as_type(Patient)):
        with pytest.raises(FHIRPathError, match="singleton"):
            evaluate([patient, patient], expression)
    for expression in (
        path().is_type("System.Missing"),
        path().as_type("System.Missing"),
        path().of_type("System.Missing"),
    ):
        with pytest.raises(FHIRPathError, match="Unknown FHIRPath type"):
            evaluate([], expression)
