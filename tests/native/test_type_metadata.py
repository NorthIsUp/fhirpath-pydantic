"""Declared FHIR primitive identity survives native field traversal."""

import pytest
from fhir.resources.observation import Observation
from fhir.resources.parameters import Parameters
from fhir.resources.patient import Patient
from fhir.resources.R4B.parameters import Parameters as R4BParameters
from fhir.resources.R4B.patient import Patient as R4BPatient
from pydantic import BaseModel

from fhirpath_pydantic import FHIRPathError, evaluate, path
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
        ("gender.is(FHIR.string)", [True]),
        ("gender.ofType(System.String)", ["female"]),
        ("gender.ofType(FHIR.string)", ["female"]),
        ("name.given.type().name", ["string", "string"]),
        ("name.given.ofType(FHIR.string)", ["Ada", "Grace"]),
        ("name.given.ofType(System.String)", ["Ada", "Grace"]),
        ("name.given.first().is(System.String)", [False]),
        ("birthDate.type().name", ["date"]),
        ("birthDate.is(FHIR.date)", [True]),
        ("Patient.type().namespace", ["FHIR"]),
        ("Patient.type().name", ["Patient"]),
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


@pytest.mark.parametrize("target", ["string1", "FHIR.string1", "System.Unknown", "Unknown.Patient", "System.Patient"])
@pytest.mark.parametrize(
    "expression",
    [
        "1.is({target})",
        "1.as({target})",
        "1.ofType({target})",
        "1 is {target}",
        "1 as {target}",
        "{{}}.ofType({target})",
        "{{}} is {target}",
    ],
)
def test_invalid_type_names_raise(target: str, expression: str) -> None:
    """A misspelled type cannot masquerade as a valid type with no matches."""
    with pytest.raises(FHIRPathError, match="type"):
        evaluate(None, expression.format(target=target))


@pytest.mark.parametrize("target", ["FHIR.Patient", "Patient", "FHIR.Resource", "System.Quantity"])
def test_valid_absent_types_remain_empty(target: str) -> None:
    """Valid declared types remain usable even when the input collection is empty."""
    assert evaluate(None, f"{{}}.ofType({target})") == []
    assert evaluate(None, f"1.ofType({target})") == []


def test_fluent_python_model_type_is_retained() -> None:
    """A typed fluent filter keeps the declared class even without a sample input."""

    class Sample(BaseModel):
        number: int

    class OtherScope:
        """A separate class may have the same unqualified name."""

        class Sample(BaseModel):
            number: int

    sample = Sample(number=1)
    query = path().of_type(Sample)
    assert evaluate([], query) == []
    assert evaluate(sample, query) == [sample]
    assert evaluate(OtherScope.Sample(number=1), query) == []


@pytest.mark.parametrize("resource_type", [Parameters, R4BParameters])
@pytest.mark.parametrize(
    ("field", "declared", "parent", "value"),
    [
        ("valueCode", "code", "string", "female"),
        ("valueId", "id", "string", "example"),
        ("valueMarkdown", "markdown", "string", "**text**"),
        ("valueCanonical", "canonical", "uri", "http://example.org/profile"),
        ("valueUrl", "url", "uri", "http://example.org"),
        ("valueOid", "oid", "uri", "urn:oid:1.2.3"),
        ("valueUuid", "uuid", "uri", "urn:uuid:79a14950-442c-41ed-b878-0242ac120002"),
        ("valuePositiveInt", "positiveInt", "integer", 1),
        ("valueUnsignedInt", "unsignedInt", "integer", 0),
    ],
)
def test_primitive_specializations_keep_parent_type(
    resource_type: type[Parameters] | type[R4BParameters], field: str, declared: str, parent: str, value: str | int
) -> None:
    """FHIR primitive inheritance supports is/as/ofType without erasing concrete identity."""
    resource = resource_type.model_validate({"parameter": [{"name": "fixture", field: value}]})
    assert evaluate(resource, "parameter.value.type().name") == [declared]
    assert evaluate(resource, "parameter.value.is(FHIR.PrimitiveType)") == [resource_type is Parameters]
    assert evaluate(resource, "parameter.value.is(FHIR.DataType)") == [resource_type is Parameters]
    assert evaluate(resource, "parameter.value.type().bases") == []
    [info] = evaluate(resource, "parameter.value.type()")
    assert isinstance(info, BaseModel)
    assert info.model_dump() == {"namespace": "FHIR", "name": declared}
    assert evaluate(resource, f"parameter.value.is(FHIR.{parent})") == [True]
    assert evaluate(resource, f"parameter.value.as(FHIR.{parent})") == evaluate(resource, "parameter.value")
    assert evaluate(resource, f"parameter.value.ofType(FHIR.{parent})") == evaluate(resource, "parameter.value")
    assert evaluate(resource, "parameter.value.is(System.String)") == [False]
    assert evaluate(resource, "parameter.value.is(System.Integer)") == [False]
