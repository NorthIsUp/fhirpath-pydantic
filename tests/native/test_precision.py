"""Native precision retains the represented digits of numeric and temporal values."""

from datetime import UTC, date, datetime, time
from decimal import Decimal, localcontext

import pytest
from fhir.resources.observation import Observation
from fhir.resources.patient import Patient
from fhir.resources.R4B.patient import Patient as R4BPatient
from pydantic import BaseModel
from test_inputs import GuardedPatient

from fhirpath_pydantic import FHIRPathError, TemporalValue, compile, evaluate, literal
from fhirpath_pydantic.types import Value


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1.58700.precision()", 5),
        ("100.precision()", 0),
        ("@2014.precision()", 4),
        ("@2014-01-05T10:30:00.000.precision()", 17),
        ("@T10:30.precision()", 4),
        ("@T10:30:00.000.precision()", 9),
    ],
)
def test_native_declared_precision(expression: str, expected: int) -> None:
    """A user can inspect decimal scale and partial temporal digits without serialization."""
    assert evaluate(None, expression) == [expected]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("@2014-01.precision()", 6),
        ("@2014-01-05.precision()", 8),
        ("@2014T.precision()", 4),
        ("@2014-01-05T10.precision()", 10),
        ("@2014-01-05T10:30.precision()", 12),
        ("@2014-01-05T10:30:00.precision()", 14),
        ("@2014-01-05T10:30:00.000000001Z.precision()", 23),
        ("@T10.precision()", 2),
        ("@T10:30:00.precision()", 6),
        ("@T10:30:00.000+10:00.precision()", 9),
        ("'2014-01-05T10:30:00.000'.toDateTime().precision()", 17),
        ("'10:30:00.000'.toTime().precision()", 9),
        ("@2014-01-05T10:30:00.000.getValue().precision()", 17),
        ("(@2014-01-05T10:30:00.000 + 1 second).precision()", 17),
        ("(@2014-01-05T10:30:00 + 1 millisecond).precision()", 17),
        ("(@T10:30:00.000 + 0.000001 's').precision()", 12),
    ],
)
def test_temporal_precision_survives_conversion_and_arithmetic(expression: str, expected: int) -> None:
    """Users retain the declared digits when temporal values pass through normal FHIRPath operations."""
    assert evaluate(None, expression) == [expected]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1.2300"), 4),
        (Decimal("1E+5"), 0),
        (Decimal("0E-30"), 30),
        (0.125, 3),
        (date(2014, 1, 5), 8),
        (datetime(2014, 1, 5, 10, 30, tzinfo=UTC), 20),
        (time(10, 30), 12),
        (TemporalValue(kind="Time", hour=10, minute=30, second=Decimal("0.000")), 9),
    ],
)
def test_precision_of_native_values_is_context_independent(value: Value, expected: int) -> None:
    """Native decimals retain trailing zeros; datetime/time expose their fixed microsecond representation."""
    with localcontext() as context:
        context.prec = 3
        assert compile(literal(value).call("precision"), output_type=int)(None) == [expected]
        assert context.prec == 3


@pytest.mark.parametrize("resource_type", [Patient, R4BPatient])
def test_fhir_partial_and_absent_dates(resource_type: type[Patient] | type[R4BPatient]) -> None:
    """A patient's partial birth date retains known digits, and an extension-only date has no scalar precision."""
    assert evaluate(resource_type.model_validate({"birthDate": "2014-01"}), "birthDate.precision()") == [6]
    patient = resource_type.model_validate({"_birthDate": {"extension": [{"url": "test", "valueString": "unknown"}]}})
    assert evaluate(patient, "birthDate.precision()") == []


def test_native_fhir_decimal_and_datetime() -> None:
    """FHIR fields expose preserved Decimal scale and the datetime representation supplied by the vendor model."""
    observation = Observation.model_validate(
        {
            "status": "final",
            "code": {"text": "fixture"},
            "valueQuantity": {"value": Decimal("1.2300"), "system": "http://unitsofmeasure.org", "code": "1"},
            "effectiveDateTime": "2014-01-05T10:30:00.000Z",
        }
    )
    assert evaluate(observation, "value.value.precision()") == [4]
    assert evaluate(observation, "effective.precision()") == [20]


@pytest.mark.parametrize(
    "expression",
    ["true.precision()", "false.precision()", "'1.23'.precision()", "(1 'mg').precision()", "(1 | 2).precision()"],
)
def test_precision_rejects_unsupported_types_and_collections(expression: str) -> None:
    """Precision queries reject invalid receivers instead of silently coercing values or picking an item."""
    with pytest.raises(FHIRPathError):
        evaluate(None, expression)


def test_empty_precision_and_wrong_arity() -> None:
    """An absent value stays absent, and argument count errors occur before evaluating unused expressions."""
    assert evaluate(None, "{}.precision()") == []
    with pytest.raises(FHIRPathError, match="Invalid argument count"):
        evaluate(None, "1.precision(%undefined)")


def test_temporal_results_remain_native_and_precision_metadata_is_call_local() -> None:
    """Returning a datetime preserves the public native API without leaking literal metadata into later calls."""
    value = compile("@2014-01-05T10:30:00.000", output_type=datetime).one(None)
    assert type(value) is datetime
    assert evaluate(value, "precision()") == [20]
    assert evaluate(None, "@2014-01-05T10:30:00.000.precision()") == [17]


def test_precision_reads_resources_without_dumping_or_revalidating(monkeypatch: pytest.MonkeyPatch) -> None:
    """A precision query keeps the caller's validated resource unchanged and never serializes it."""
    patient = GuardedPatient.model_validate({"birthDate": "2014-01"})
    before = GuardedPatient.validations

    def reject_dump(self: BaseModel) -> None:
        raise AssertionError("Precision must not serialize a resource")

    monkeypatch.setattr(BaseModel, "model_dump", reject_dump)
    assert evaluate(patient, "birthDate.precision()") == [6]
    assert patient.birthDate == "2014-01"
    assert GuardedPatient.validations == before


def test_precision_metadata_does_not_copy_native_datetime_values() -> None:
    """Inspecting a native FHIR datetime keeps the original scalar object when exposing its System value."""
    observation = Observation.model_validate(
        {
            "status": "final",
            "code": {"text": "fixture"},
            "effectiveDateTime": "2014-01-05T10:30:00.000Z",
        }
    )
    assert evaluate(observation, "effective.getValue()")[0] is observation.effectiveDateTime
    assert evaluate(observation, "effective.getValue().precision()") == [20]
