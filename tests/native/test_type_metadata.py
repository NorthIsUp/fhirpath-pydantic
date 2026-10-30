"""Declared FHIR primitive identity survives native field traversal."""

import pytest
from fhir.resources.observation import Observation
from fhir.resources.patient import Patient
from fhir.resources.R4B.patient import Patient as R4BPatient

from fhirpath_pydantic import evaluate
from fhirpath_pydantic.types import Collection


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("active.type().namespace", ["FHIR"]),
        ("active.type().name", ["boolean"]),
        ("active is FHIR.boolean", [True]),
        ("active is boolean", [True]),
        ("active.is(Boolean)", [False]),
        ("active.is(System.Boolean)", [False]),
        ("active.ofType(System.Boolean)", [True]),
        ("active.getValue().is(System.Boolean)", [True]),
        ("active.getValue().type().namespace", ["System"]),
        ("active.getValue().type().name", ["Boolean"]),
        ("gender.type().name", ["code"]),
        ("gender.is(FHIR.code)", [True]),
        ("gender.is(FHIR.string)", [False]),
        ("gender.ofType(System.String)", ["female"]),
        ("gender.ofType(FHIR.string)", []),
        ("name.given.type().name", ["string", "string"]),
        ("name.given.ofType(FHIR.string)", ["Ada", "Grace"]),
        ("name.given.ofType(System.String)", ["Ada", "Grace"]),
        ("name.given.first().is(System.String)", [False]),
        ("birthDate.type().name", ["date"]),
        ("birthDate.is(FHIR.date)", [True]),
        ("Patient.type().namespace", ["FHIR"]),
        ("Patient.type().name", ["Patient"]),
        ("Patient.is(System.Patient)", [False]),
        ("Patient.is(FHIR.Resource)", [True]),
        ("active.is(FHIR.Element)", [True]),
        ("active.hasValue()", [True]),
    ],
)
def test_declared_primitive_types(expression: str, expected: Collection) -> None:
    """FHIR and System identity remain distinct even with identical Python values."""
    patient = Patient.model_validate(
        {"active": True, "gender": "female", "birthDate": "2018", "name": [{"given": ["Ada", "Grace"]}]}
    )
    assert evaluate(patient, expression) == expected
    r4b = R4BPatient.model_validate(
        {"active": True, "gender": "female", "birthDate": "2018", "name": [{"given": ["Ada", "Grace"]}]}
    )
    assert evaluate(r4b, expression) == expected


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1.type().name", ["Integer"]),
        ("true.type().namespace", ["System"]),
        ("'text'.type().name", ["String"]),
        ("(1 'g').type().name", ["Quantity"]),
        ("@2018.type().name", ["Date"]),
        ("{}.type()", []),
        ("'text'.is(FHIR.code)", [False]),
        ("1.is(FHIR.positiveInt)", [False]),
    ],
)
def test_system_literals_have_no_fhir_subtype(expression: str, expected: Collection) -> None:
    """System values cannot acquire a FHIR primitive type from their representation."""
    assert evaluate(None, expression) == expected


def test_extension_only_primitive_has_declared_type() -> None:
    """A primitive may have a declared FHIR type and extensions without a value."""
    patient = Patient.model_validate(
        {"_active": {"extension": [{"url": "http://example.org/absent", "valueString": "unknown"}]}}
    )
    assert evaluate(patient, "active.type().name") == ["boolean"]
    assert evaluate(patient, "active.is(FHIR.boolean)") == [True]
    assert evaluate(patient, "active.getValue()") == []


def test_choice_field_retains_declared_subtype() -> None:
    """Choice navigation reads the selected field's metadata instead of guessing."""
    observation = Observation.model_validate({"status": "final", "code": {"text": "synthetic"}, "valueString": "text"})
    assert evaluate(observation, "value.type().name") == ["string"]
    assert evaluate(observation, "value.is(FHIR.code)") == [False]
    assert evaluate(observation, "value.ofType(System.String)") == ["text"]


def test_partial_fhir_temporal_uses_declared_type_in_operations() -> None:
    """A FHIR partial date stored as text has temporal semantics without input rewriting."""
    patient = Patient.model_validate({"birthDate": "2018"})
    assert evaluate(patient, "birthDate = @2018") == [True]
    assert evaluate(patient, "birthDate = @2018-01") == []
    assert evaluate(patient, "birthDate + 1 year = @2019") == [True]
    assert evaluate(patient, "birthDate.getValue().is(System.DateTime)") == [True]
    assert patient.birthDate == "2018"


def test_primitive_id_comes_from_extension_companion() -> None:
    """Primitive metadata is accessible without serializing or replacing its value."""
    patient = Patient.model_validate({"active": True, "_active": {"id": "synthetic"}})
    assert evaluate(patient, "active.id") == ["synthetic"]
