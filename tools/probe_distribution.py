"""Run only through the isolated built-wheel smoke task."""

from decimal import Decimal
from os import environ
from pathlib import Path
from sys import modules
from typing import ClassVar, Self

from fhir.resources.patient import Patient
from pydantic import BaseModel, Field, model_validator

import fhirpath_pydantic
from fhirpath_pydantic import (
    CustomMacro,
    EvaluationOptions,
    FHIRPathConstraint,
    FunctionArity,
    MacroCall,
    compile,
    evaluate,
    literal,
    path,
    var,
)
from fhirpath_pydantic.types import Collection


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


class ChoicePolicy(BaseModel):
    """A Pydantic-owned callback policy controls deferred variadic selection."""

    minimum_results: int = Field(default=1, ge=1, strict=True)

    def first_present(self, call: MacroCall) -> Collection:
        """Return the first populated argument without evaluating later expressions."""
        for argument in call.arguments:
            if len(result := argument.evaluate()) >= self.minimum_results:
                return result
        return []


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
    policy = ChoicePolicy()
    options = EvaluationOptions(
        functions=(CustomMacro(name="firstPresent", handler=policy.first_present, arity=FunctionArity(minimum=1)),)
    )
    expression = path().call("firstPresent", literal([]), literal(patient), var("undefined"))
    assert evaluate(None, expression, options=options)[0] is patient
    assert ActivePatient.validations == before, "macro revalidated the resource"
    assert evaluate(None, literal(Decimal("1.2300")).call("precision")) == [4]
    assert evaluate(None, "@2014-01-05T10:30:00.000.precision()") == [17]
    assert not any(name == "fhirpathpy" or name.startswith("fhirpathpy.") for name in modules)
    print("Built wheel: native inputs, fluent/text queries, profile validators and constraints passed")


if __name__ == "__main__":
    main()
