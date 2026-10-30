"""Precision-aware temporal behavior on native values and parsed literals."""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from pydantic import ValidationError

from fhirpath_pydantic import TemporalValue, evaluate, literal
from fhirpath_pydantic.types import Collection


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("@2018 = @2018", [True]),
        ("@2018 = @2018-01", []),
        ("@2018 != @2018-01", []),
        ("@2018 = @2019-01", [False]),
        ("@2018 < @2019-01", [True]),
        ("@2018-01 ~ @2018-01-01", [False]),
        ("@2018-01 !~ @2018-01-01", [True]),
        ("@2018-02-02T11 = @2018-02-02T11:00", []),
        ("@2018-02-02T11 < @2018-02-02T11:01", []),
        ("@2018-02-02T10 < @2018-02-02T11:01", [True]),
        ("@2018-02-02 = @2018-02-02T11:00:00", []),
        ("@2018-02-02T22-04:00 = @2018-02-03T06:03+04:00", []),
        ("@T12 = @T12:00", []),
        ("@T12:01 > @T12", []),
        ("@T19:01:23-05:00 = @T00:01:23Z", [True]),
        ("@T10:04:23-04:00 = @T14:04Z", []),
        ("@T12:00:00 = @T12:00:00.000", [True]),
        ("@T12:00:00.001 < @T12:00:00.010", [True]),
        ("'2018'.toDateTime() is DateTime", [True]),
        ("@2018 is Date", [True]),
        ("@T12 is Time", [True]),
        ("'2018'.convertsToDate()", [True]),
        ("'2018-02'.convertsToDateTime()", [True]),
        ("'2018-02'.toDate().toString()", ["2018-02"]),
        ("'12:30'.toTime().toString()", ["12:30"]),
    ],
)
def test_precision_semantics(expression: str, expected: Collection) -> None:
    """A missing component remains unknown rather than being padded with zero."""
    assert evaluate(None, expression) == expected


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("@2018-02-02", date(2018, 2, 2)),
        ("@2018-02-02T11:30:01", datetime(2018, 2, 2, 11, 30, 1)),
        ("@T11:30:01", time(11, 30, 1)),
    ],
)
def test_complete_temporals_remain_native(expression: str, expected: date | time) -> None:
    """Complete literals continue returning standard-library temporal values."""
    [actual] = evaluate(None, expression)
    assert type(actual) is type(expected)
    assert actual == expected


@pytest.mark.parametrize(
    "text",
    [
        "2019-02-29",
        "2018-13",
        "0000",
        "2018-01-01T24:00",
        "2018-01-01T12:60",
        "2018-01-01T12:30:60",
        "2018-01-01T12:30+14:01",
        "2018-01-01T12:30+01:99",
    ],
)
def test_invalid_temporal_components_rejected(text: str) -> None:
    """Construction validates actual calendars, ranges and timezone components."""
    with pytest.raises(ValueError):
        TemporalValue.from_text(text, "DateTime" if "T" in text else "Date")


def test_missing_intermediate_component_rejected() -> None:
    """Direct constructors enforce the same precision invariants as parsing."""
    with pytest.raises(ValidationError):
        TemporalValue(kind="DateTime", year=2018, hour=12)


def test_native_partial_literal_needs_no_query_string() -> None:
    """Partial DateTime values compose directly even beyond inherited grammar syntax."""
    value = TemporalValue(kind="DateTime", year=2018)
    assert evaluate(None, literal(value).eq(literal(value))) == [True]
    assert evaluate(None, literal(value))[0] is value


def test_submicrosecond_precision_is_preserved() -> None:
    """Higher precision stays on the model instead of being truncated by datetime."""
    value = TemporalValue.from_text("12:30:00.0000001", "Time")
    assert value.native() is value
    assert str(value) == "12:30:00.0000001"
    assert evaluate(None, "@T12:30:00.0000001 > @T12:30:00") == [True]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("(@2016-02-29 + 1 year).toString()", ["2017-02-28"]),
        ("(@2016-01-31 + 1 month).toString()", ["2016-02-29"]),
        ("(@2016-01-31 - 1 month).toString()", ["2015-12-31"]),
        ("(@2016-02-28 + 1.5 weeks).toString()", ["2016-03-06"]),
        ("(@2016-02-28 + 1.5 day).toString()", ["2016-02-29"]),
        ("(@2016 + 365 days).toString()", ["2017"]),
        ("(@2016 + 364 days).toString()", ["2016"]),
        ("(@2016 - 365 days).toString()", ["2015"]),
        ("(@2016 + 23 months).toString()", ["2017"]),
        ("(@2016-01 + 30 days).toString()", ["2016-02"]),
        ("(@2018-02-18T12 + 59 minutes).toString()", ["2018-02-18T12"]),
        ("(@2018-02-18T12 + 60 minutes).toString()", ["2018-02-18T13"]),
        ("@T23:59:23 + 2 minutes = @T00:01:23", [True]),
        ("@T23:59:23 - 1.5 's' = @T23:59:21.500", [True]),
        ("@T23:59:23 + 5 milliseconds = @T23:59:23.005", [True]),
        ("@T23:59:23 + 1.5 hours = @T00:59:23", [True]),
        ("@T23:59:23.0000001 + 0.0000001 's' = @T23:59:23.0000002", [True]),
    ],
)
def test_calendar_arithmetic(expression: str, expected: Collection) -> None:
    """Calendar adjustment clamps dates, truncates coarse units and retains precision."""
    assert evaluate(None, expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "@2018 + 1 'a'",
        "@2018-02 + 1 'mo'",
        "@2018-02-01 + 1 'd'",
        "@T12 + 1 day",
        "@T12 + 1 year",
        "@2018-02-01 + 1 'kg'",
        "@9999 + 1 year",
        "@0001 - 1 year",
    ],
)
def test_invalid_temporal_arithmetic(expression: str) -> None:
    """Noncalendar coarse units, incompatible dimensions and overflow are errors."""
    with pytest.raises(ValueError):
        evaluate(None, expression)


@pytest.mark.parametrize("text", ["2018T", "2018-02T", "2018-02-02T"])
def test_date_only_datetime_literals(text: str) -> None:
    """A trailing T explicitly retains the DateTime type at partial date precision."""
    assert evaluate(None, f"@{text}.type().name") == ["DateTime"]
    assert evaluate(None, f"@{text}.toString()") == [text]


@pytest.mark.parametrize("text", ["2018T12", "2018-02T12:30", "2018TZ", "2018-02-02TZ"])
def test_datetime_literal_precision_holes_are_rejected(text: str) -> None:
    """Lexical date/time tokens must still satisfy Pydantic precision invariants."""
    with pytest.raises(ValueError):
        evaluate(None, f"@{text}")


@pytest.mark.parametrize(("amount", "microseconds"), [("0.1", 100_000), ("0.01", 10_000), ("0.001", 1_000)])
def test_fractional_second_addition(amount: str, microseconds: int) -> None:
    """Second fractions survive addition to a native full-precision DateTime."""
    expression = f"@1973-12-25T00:00:00.000+10:00 + {amount} 's'"
    expected = datetime(1973, 12, 25, microsecond=microseconds, tzinfo=timezone(timedelta(hours=10)))
    assert evaluate(None, expression) == [expected]
