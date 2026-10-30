"""Run only through the isolated built-wheel smoke task."""

from os import environ
from pathlib import Path
from sys import modules
from typing import ClassVar, Self

from fhir.resources.patient import Patient
from pydantic import model_validator

import fhirpath_pydantic
from fhirpath_pydantic import FHIRPathConstraint, compile, evaluate, path, var


class ActivePatient(Patient):
    """A native profile exposes accidental validation or lost subclass identity."""

    validations: ClassVar[int] = 0

    @model_validator(mode="after")
    def active_required(self) -> Self:
        """Retain an ordinary caller-owned Pydantic invariant."""
        type(self).validations += 1
        if self.active is not True:
            raise ValueError("An active patient is required")
        return self


def main() -> None:
    """Exercise native resources, fluent/text queries and Pydantic constraints from the archive."""
    wheel = Path(environ["FHIRPATH_WHEEL"])
    assert fhirpath_pydantic.__file__ is not None
    assert Path(fhirpath_pydantic.__file__).is_relative_to(wheel), fhirpath_pydantic.__file__
    patient = ActivePatient.model_validate({"active": True, "name": [{"use": "official", "given": ["wheel"]}]})
    before = ActivePatient.validations
    assert before > 0
    query = compile(path("name").where(path("use").eq(var("use"))).field("given").first(), output_type=str)
    assert query(patient, {"use": "official"}) == ["wheel"]
    assert ActivePatient.validations == before, "fluent query revalidated the resource"
    assert evaluate(patient, "Patient.name.given.first()") == ["wheel"]
    assert ActivePatient.validations == before, "text query revalidated the resource"
    assert evaluate(patient, path().as_type(Patient))[0] is patient
    assert ActivePatient.validations == before, "native type test revalidated the resource"
    assert FHIRPathConstraint(expression="active = true").check(patient) is patient
    assert ActivePatient.validations == before, "constraint revalidated the resource"
    assert not any(name == "fhirpathpy" or name.startswith("fhirpathpy.") for name in modules)
    print("Built wheel: native inputs, fluent/text queries, profile validators and constraints passed")


if __name__ == "__main__":
    main()
