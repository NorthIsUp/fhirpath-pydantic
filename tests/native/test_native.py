"""Native-model regressions and public API contracts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from typing import Annotated

import pytest
from fhir.resources.humanname import HumanName
from fhir.resources.observation import Observation
from fhir.resources.patient import Patient
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.patient import Patient as R4BPatient
from pydantic import BaseModel, ValidationError

from fhirpath_pydantic import FHIRPathConstraint, FHIRPathError, compile, evaluate, literal, path, var
from fhirpath_pydantic.types import Collection


@pytest.fixture
def patient() -> Patient:
    """Names and date are literals because these exact values are under test."""
    return Patient.model_validate(
        {
            "active": True,
            "birthDate": "2000-02-29",
            "name": [
                {"use": "official", "family": "O'Neil", "given": ["Zoë", "Ada"]},
                {"use": "usual", "given": ["Z"]},
            ],
        }
    )


def test_identity(patient: Patient) -> None:
    """Complex results are the original model instances."""
    assert patient.name is not None
    assert evaluate(patient, "Patient.name.first()")[0] is patient.name[0]
    assert evaluate(patient, "$this")[0] is patient


def test_no_dump(patient: Patient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native evaluation never falls back to model_dump."""

    def reject_dump(self: BaseModel) -> None:
        raise AssertionError("model_dump called")

    monkeypatch.setattr(BaseModel, "model_dump", reject_dump)
    assert evaluate(patient, "Patient.name.given.first()") == ["Zoë"]


def test_alias() -> None:
    """FHIR class resolves to Encounter.class_fhir."""
    encounter = Encounter.model_validate({"status": "finished", "class": {"code": "AMB"}})
    assert evaluate(encounter, "Encounter.class.code") == ["AMB"]
    assert evaluate(encounter, "class")[0] is encounter.class_fhir


def test_choices() -> None:
    """Choice groups preserve native Quantity and Decimal values."""
    resource = Observation.model_validate(
        {
            "status": "final",
            "code": {"text": "quantity-test"},
            "valueQuantity": {"value": Decimal("1.2300"), "unit": "mg"},
        }
    )
    assert evaluate(resource, "Observation.value")[0] is resource.valueQuantity
    assert evaluate(resource, "value.ofType(Quantity).value") == [Decimal("1.2300")]
    assert isinstance(evaluate(resource, "value.value")[0], Decimal)


def test_false_and_zero() -> None:
    """Falsy populated choice fields remain populated."""
    assert evaluate(Patient.model_validate({"deceasedBoolean": False}), "deceased") == [False]
    assert evaluate(
        R4BPatient.model_validate({"active": False, "multipleBirthInteger": 0}), "Patient.multipleBirth"
    ) == [0]


def test_dates(patient: Patient) -> None:
    """Full precision native dates compare to temporal literals."""
    assert evaluate(patient, "birthDate") == [date(2000, 2, 29)]
    assert evaluate(patient, "birthDate = @2000-02-29") == [True]


def test_variables(patient: Patient) -> None:
    """Quoted user data remains data, without interpolation or context mutation."""
    context = {"family": "O'Neil"}
    assert evaluate(patient, "name.where(family = %family).given.first()", context) == ["Zoë"]
    assert context == {"family": "O'Neil"}
    assert evaluate(patient, "name.where(family = %family)", {"family": "' or true or '"}) == []


def test_builder(patient: Patient) -> None:
    """Fluent expressions execute nodes without rendering or parsing strings."""
    query = path("Patient", "name").where(path("family").eq(var("family"))).field("given").first()
    assert evaluate(patient, query, {"family": "O'Neil"}) == ["Zoë"]
    assert evaluate(patient, path("name").where(path("family").eq(literal("O'Neil"))).field("given").first()) == ["Zoë"]


def test_primitive_extensions() -> None:
    """Extension-only primitives are traversable without inventing a scalar."""
    resource = Patient.model_validate(
        {"_birthDate": {"extension": [{"url": "http://example.org/unknown", "valueCode": "unknown"}]}}
    )
    assert evaluate(resource, "birthDate") == []
    assert evaluate(resource, "birthDate.hasValue()") == [False]
    assert evaluate(resource, "birthDate.extension.value") == ["unknown"]
    assert evaluate(resource, "birthDate.extension('http://example.org/unknown').value") == ["unknown"]


def test_extension_alignment() -> None:
    """Null primitive slots retain their matching extension slots."""
    resource = Patient.model_validate(
        {
            "name": [
                {
                    "given": [None, "Zoë"],
                    "_given": [{"extension": [{"url": "http://example.org/test", "valueString": "missing"}]}, None],
                }
            ]
        }
    )
    assert evaluate(resource, "name.given[0].hasValue()") == [False]
    assert evaluate(resource, "name.given[0].extension.value") == ["missing"]
    assert evaluate(resource, "name.given[1]") == ["Zoë"]


def test_typed_result(patient: Patient) -> None:
    """Reusable TypeAdapters strictly validate results and preserve identity."""
    query = compile("name", output_type=HumanName)
    assert patient.name is not None
    assert query(patient)[0] is patient.name[0]
    assert compile("active", output_type=bool)(patient) == [True]
    with pytest.raises(ValidationError):
        compile("active", output_type=str)(patient)


def test_validator(patient: Patient) -> None:
    """FHIRPath invariants compose with Pydantic Annotated validators."""
    constraint = FHIRPathConstraint(expression="active = true", message="Resource must be active")

    class Envelope(BaseModel):
        resource: Annotated[Patient, constraint.after_validator()]

    assert Envelope(resource=patient).resource is patient
    with pytest.raises(ValidationError, match="Resource must be active"):
        Envelope.model_validate({"resource": {"active": False}})


def test_concurrency(patient: Patient) -> None:
    """Threads deliberately exercise reuse of this synchronous CPU-only engine."""
    query = compile("name.where(use = %use).given.first()", output_type=str)
    contexts = [{"use": "official"}, {"use": "usual"}] * 30

    def run(context: dict[str, str]) -> list[str]:
        return query(patient, context)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(run, contexts))
    assert results == [["Zoë"], ["Z"]] * 30


@pytest.mark.parametrize(
    "expression", ["", "name trailing", "name.where(", "name ???", "name[", "name.where(use = 'unterminated)"]
)
def test_bad_syntax(patient: Patient, expression: str) -> None:
    """Lexer errors, parser recovery and trailing tokens fail closed."""
    with pytest.raises(FHIRPathError):
        evaluate(patient, expression)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("{}.empty()", [True]),
        ("{}.exists()", [False]),
        ("{}.all(true)", [True]),
        ("{} and false", [False]),
        ("{} or true", [True]),
        ("{} xor true", []),
        ("false implies {}", [True]),
        ("{} implies true", [True]),
        ("{} = {}", []),
        ("{} ~ {}", [True]),
        ("{} & 'x'", ["x"]),
        ("(1 | 2 | 3).where($this > 1)", [2, 3]),
        ("(1 | 2 | 3).select($index)", [0, 1, 2]),
        ("(1 | 2 | 3).aggregate($total + $this, 0)", [6]),
        ("(1 | 2).all($this > 0)", [True]),
        ("iif(true, 'yes', %undefined)", ["yes"]),
        ("false and %undefined", [False]),
        ("'AbC'.lower()", ["abc"]),
        ("'abc'.substring(1, 1)", ["b"]),
        ("'O\\'Neil'", ["O'Neil"]),
        ("'\\u00eb'", ["ë"]),
        ("'true'.toBoolean()", [True]),
        ("'1.2'.toDecimal()", [Decimal("1.2")]),
        ("'bad'.convertsToInteger()", [False]),
        ("(1 | 2).count()", [2]),
        ("(1 | 2).skip(-1)", [1, 2]),
        ("3 / 0", []),
        ("(-5) div 2", [-2]),
        ("1.25.round(1)", [Decimal("1.3")]),
    ],
)
def test_semantics(expression: str, expected: Collection) -> None:
    """Collection, Boolean, variable and numeric semantics follow FHIRPath."""
    assert evaluate(None, expression) == expected


def test_cardinality(patient: Patient) -> None:
    """Singleton operations and function arities reject invalid inputs."""
    with pytest.raises(FHIRPathError, match="singleton"):
        evaluate(patient, "name.single()")
    with pytest.raises(FHIRPathError, match="argument count"):
        evaluate(patient, "name.first(1)")
