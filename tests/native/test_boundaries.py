"""Boundary cases for native scalar conversion, cardinality and traversal."""

from datetime import date, datetime, time
from decimal import Decimal

import pytest
from fhir.resources.humanname import HumanName
from fhir.resources.patient import Patient
from pydantic import BaseModel, TypeAdapter

from fhirpath_pydantic import CompiledQuery, FHIRPathError, compile, evaluate, literal, path
from fhirpath_pydantic import query as query_module
from fhirpath_pydantic.types import Collection


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("true = true", [True]),
        ("false = false", [True]),
        ("true = 1", [False]),
        ("(1 + 2) is Integer", [True]),
        ("(-2) is Integer", [True]),
        ("9223372036854775807 mod 2", [1]),
        ("(-5) mod 2", [-1]),
        ("{} and true", []),
        ("{} or false", []),
        ("{} implies false", []),
        ("{} !~ {}", [False]),
        ("(1 | 2) ~ (2 | 1)", [True]),
        ("1 in {}", [False]),
        ("{} contains 1", [False]),
        ("{} in (1 | 2)", []),
        ("true.toString()", ["true"]),
        ("false.toString()", ["false"]),
        ("1.toString()", ["1"]),
        ("true.toBoolean()", [True]),
        ("0.toBoolean()", [False]),
        ("'n'.toBoolean()", [False]),
        ("true.toInteger()", [1]),
        ("false.toDecimal()", [Decimal(0)]),
        ("'invalid'.toDecimal()", []),
        ("'invalid'.toBoolean()", []),
        ("'2000-02-29'.toDate()", [date(2000, 2, 29)]),
        ("'2000-02-29T12:30:00'.toDateTime()", [datetime(2000, 2, 29, 12, 30)]),
        ("'12:30:00'.toTime()", [time(12, 30)]),
        ("'invalid'.toDate()", []),
        ("'invalid'.toDateTime()", []),
        ("'invalid'.toTime()", []),
        ("{}.toString()", []),
        ("{}.toInteger()", []),
        ("{}.sqrt()", []),
        ("(-1).sqrt()", []),
        ("1.exp() > 2", [True]),
        ("1.ln()", [Decimal(0)]),
        ("0.ln()", []),
        ("8.log(1)", []),
        ("8.log(2)", [Decimal(3)]),
        ("'abc'.substring(-1)", []),
        ("'abc'.substring(9)", []),
        ("'abc'.substring(1, -1)", [""]),
        ("'abc'.contains({})", []),
        ("('a' | 'b').join(',')", ["a,b"]),
        ("{}.join()", [""]),
        ("coalesce({}, 1, %undefined)", [1]),
        ("coalesce({}, {})", []),
        ("iif(false, %undefined)", []),
        ("iif(false, %undefined, 2)", [2]),
        ("(1 | 2).where($this > 9)", []),
        ("(1 | 2).exists($this > 9)", [False]),
        ("(1 | 2).all($this > 1)", [False]),
        ("1.as(Integer)", [1]),
        ("1.as(String)", []),
        ("{} as Integer", []),
        ("@2000-02-29 < @2000-03-01", [True]),
        ("@T12:30:00 < @T13:00:00", [True]),
    ],
)
def test_scalar_boundaries(expression: str, expected: Collection) -> None:
    """Empty values, failed conversions and native representations stay distinct."""
    assert evaluate(None, expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "(1 | 2).not()",
        "1 and (1 | 2)",
        "true < false",
        "'x' > 1",
        "1.length()",
        "(true | 1).allTrue()",
        "(1 | 2).join()",
        "1.round(-1)",
        "'x'.skip(1.2)",
    ],
)
def test_rejects_incompatible_values(expression: str) -> None:
    """Invalid cardinality and argument types never coerce silently."""
    with pytest.raises(FHIRPathError):
        evaluate(None, expression)


def test_native_traversal() -> None:
    """Children, descendants and repetition traverse nested native objects."""
    resource = Patient.model_validate({"active": False, "name": [{"given": ["traversal"]}]})
    assert resource.name is not None
    assert resource.name[0] in evaluate(resource, "children()")
    assert "traversal" in evaluate(resource, "descendants()")
    assert "traversal" in evaluate(resource, "repeat(children())")
    assert evaluate(resource, "name.given.getValue()") == ["traversal"]
    assert evaluate(resource, "name.hasValue()") == [False]
    assert evaluate(resource, "resourceType") == ["Patient"]
    assert evaluate(resource, "Observation") == []


def test_dict_and_pydantic() -> None:
    """Plain Pydantic models and raw mappings have predictable ordinary fields."""

    class Sample(BaseModel):
        active: bool

    assert evaluate(Sample(active=False), "active") == [False]
    assert evaluate({"resourceType": "Patient", "active": False}, "Patient.active") == [False]
    assert evaluate({"active": False}, "children()") == [False]


def test_fluent_without_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Builder nodes reach the evaluator directly without a text round trip."""

    def reject(expression: str) -> None:
        raise AssertionError("Parser must not run for fluent queries")

    monkeypatch.setattr(query_module, "parse", reject)
    resource = Patient.model_validate({"name": [{"given": ["builder"]}]})
    expression = path("name").of_type(HumanName).select(path("given")).first()
    assert evaluate(resource, expression) == ["builder"]
    assert evaluate(resource, literal(False).ne(literal(True)).and_(literal(2).gt(literal(1))).or_(literal(False))) == [
        True
    ]
    assert evaluate(resource, path("name").exists()) == [True]


def test_query_cardinality() -> None:
    """First and one distinguish empty, singleton and multiple results."""
    query = compile("(1 | 2)", output_type=int)
    assert query.first(None) == 1
    with pytest.raises(FHIRPathError, match="singleton"):
        query.one(None)
    assert compile("{}", output_type=int).one(None) is None
    assert compile("1", output_type=int).one(None) == 1


def test_custom_result_adapter() -> None:
    """A caller may reuse a Pydantic result adapter without changing evaluation."""
    query = CompiledQuery[int](node=literal(1).node, adapter=TypeAdapter[int](int))
    assert query(None) == [1]


def test_clock_is_stable_within_one_evaluation() -> None:
    """Repeated clock functions use one evaluation timestamp, as FHIRPath requires."""
    assert evaluate(None, "now() = now()") == [True]
    assert evaluate(None, "timeOfDay() = timeOfDay()") == [True]
