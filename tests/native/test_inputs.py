"""Native collections and readonly containers are valid typed evaluation inputs."""

from collections.abc import Generator
from types import MappingProxyType
from typing import ClassVar, Self, override

from fhir.resources.patient import Patient
from pydantic import TypeAdapter, model_validator

from fhirpath_pydantic import InputValue, compile, evaluate, literal


class GuardedPatient(Patient):
    """A resource exposes accidental iteration or repeated model validation."""

    validations: ClassVar[int] = 0

    @model_validator(mode="after")
    def record_validation(self) -> Self:
        """Count actual vendor-model validation rather than wrapper validation."""
        type(self).validations += 1
        return self

    @override
    def __iter__(self) -> Generator[tuple[str, str]]:
        """Reject collection coercion of an existing resource."""
        raise AssertionError("Resources must not be coerced through collection iteration")


def test_typed_resource_lists_work_across_public_query_methods() -> None:
    """A list of a concrete FHIR type needs no cast to the library's mutable Value list."""
    patients: list[Patient] = [Patient.model_validate({"name": [{"given": [name]}]}) for name in ("a", "b")]
    query = compile("name.given", output_type=str)
    assert query(patients) == ["a", "b"]
    assert query.first(patients) == "a"
    assert compile("name.given.first()", output_type=str).one(patients) == "a"
    assert evaluate(patients, "name.given") == ["a", "b"]
    assert evaluate(None, literal(patients).field("name").field("given")) == ["a", "b"]
    context: dict[str, list[Patient]] = {"patients": patients}
    assert evaluate(None, "%patients.name.given", context) == ["a", "b"]


def test_readonly_sequences_flatten_without_revalidating_resources() -> None:
    """Tuple normalization preserves each resource's identity and invariants."""
    patient = GuardedPatient.model_validate({"name": [{"given": ["a"]}]})
    before = GuardedPatient.validations
    patients: tuple[GuardedPatient, ...] = (patient,)
    assert evaluate(patients, "name.given") == ["a"]
    assert evaluate(patients, "$this")[0] is patient
    assert evaluate(None, literal(patients))[0] is patient
    assert GuardedPatient.validations == before


def test_readonly_mappings_and_context_remain_native() -> None:
    """Open mappings normalize at the public boundary without dumping native children."""
    patient = GuardedPatient.model_validate({"active": True})
    before = GuardedPatient.validations
    subject = MappingProxyType({"patient": patient})
    context = MappingProxyType({"subjects": (patient,)})
    assert evaluate(subject, "patient")[0] is patient
    assert evaluate(None, "%subjects", context)[0] is patient
    assert subject["patient"] is patient
    assert context["subjects"] == (patient,)
    assert GuardedPatient.validations == before


def test_public_input_alias_supports_pydantic_boundaries() -> None:
    """The covariant input contract also remains usable in native Pydantic schemas."""
    patient = GuardedPatient.model_validate({"active": True})
    before = GuardedPatient.validations
    adapter = TypeAdapter[InputValue](InputValue)
    assert adapter.validate_python(patient, strict=True) is patient
    assert adapter.json_schema()["$defs"]
    assert GuardedPatient.validations == before
