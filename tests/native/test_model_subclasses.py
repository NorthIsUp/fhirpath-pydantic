"""FHIR model validators and subclasses retain their logical FHIR identity."""

from typing import Self

import pytest
from fhir.resources.patient import Patient
from pydantic import ValidationError, model_validator

from fhirpath_pydantic import compile, evaluate


class ActivePatient(Patient):
    """A caller-defined FHIR resource with an ordinary Pydantic invariant."""

    @model_validator(mode="after")
    def must_be_active(self) -> Self:
        """Validate at the resource boundary rather than inside the query runtime."""
        if self.active is not True:
            raise ValueError("This patient profile requires active=true")
        return self


def test_native_subclass_keeps_fhir_resource_type() -> None:
    """Pydantic profiles retain the logical Patient type and original instance."""
    patient = ActivePatient.model_validate({"id": "profile", "active": True})
    assert evaluate(patient, "Patient.active") == [True]
    assert evaluate(patient, "resourceType") == ["Patient"]
    assert compile("Patient", output_type=Patient)(patient)[0] is patient


def test_native_subclass_validator_still_runs() -> None:
    """The evaluator accepts validated resources without bypassing their construction rules."""
    with pytest.raises(ValidationError, match="profile requires"):
        ActivePatient.model_validate({"active": False})
