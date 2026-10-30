"""FHIR-defined variables resolve within each native evaluation scope."""

import pytest
from fhir.resources.patient import Patient

from fhirpath_pydantic import FHIRPathError, compile, evaluate


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("%sct", "http://snomed.info/sct"),
        ("%loinc", "http://loinc.org"),
        ("%ucum", "http://unitsofmeasure.org"),
        ("%`vs-administrative-gender`", "http://hl7.org/fhir/ValueSet/administrative-gender"),
        ("%`ext-patient-birthTime`", "http://hl7.org/fhir/StructureDefinition/patient-birthTime"),
    ],
)
def test_standard_variables(expression: str, expected: str) -> None:
    """Standard canonical identifiers require no caller-provided substitutions."""
    assert evaluate(None, expression) == [expected]


@pytest.mark.parametrize("name", ["sct", "loinc", "ucum", "vs-administrative-gender", "ext-patient-birthTime"])
def test_caller_variables_override_defaults_per_call(name: str) -> None:
    """Compiled queries do not retain one call's explicit environment bindings."""
    query = compile(f"%`{name}`")
    assert query(None, {name: "http://example.org/override"}) == ["http://example.org/override"]
    assert query(None) != ["http://example.org/override"]
    assert query(None, {name: None}) == []


@pytest.mark.parametrize("name", ["unknown", "vs-", "ext-", "vs-bad/name"])
def test_undefined_variables_still_raise(name: str) -> None:
    """Unknown names and invalid canonical ids are not silently expanded."""
    with pytest.raises(FHIRPathError, match="Undefined"):
        evaluate(None, f"%`{name}`")


def test_standard_extension_variable_on_native_model() -> None:
    """An extension URL resolves inside native navigation without expression interpolation."""
    patient = Patient.model_validate(
        {
            "_birthDate": {
                "extension": [
                    {"url": "http://hl7.org/fhir/StructureDefinition/patient-birthTime", "valueString": "synthetic"}
                ]
            }
        }
    )
    assert evaluate(patient, "birthDate.extension(%`ext-patient-birthTime`).value") == ["synthetic"]
