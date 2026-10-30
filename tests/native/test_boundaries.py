"""Boundary cases for native scalar conversion, cardinality and traversal."""

from collections.abc import Generator
from datetime import date, datetime, time
from decimal import Decimal, localcontext
from typing import Annotated, Self, override

import pytest
from fhir.resources.humanname import HumanName
from fhir.resources.patient import Patient
from fhir.resources.R4B.patient import Patient as R4BPatient
from pydantic import BaseModel, PrivateAttr, TypeAdapter, ValidationError, model_validator

from fhirpath_pydantic import CompiledQuery, FHIRPathError, QuantityValue, compile, evaluate, literal, path
from fhirpath_pydantic import query as query_module
from fhirpath_pydantic.types import Collection, NativeModel, Value


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
        ("(0 | 1 | 2).skip({})", []),
        ("{}.skip({})", []),
        ("(0 | 1 | 2).take({})", []),
        ("{}.take({})", []),
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
        ("{}.join()", []),
        ("{}.join(',')", []),
        ("''.join()", [""]),
        ("('' | 'a').join(',')", [",a"]),
        ("'a'.join({})", []),
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
        "('item1' | 'item2').iif(true, 'yes', 'no')",
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


def test_value_validation_preserves_nested_mappings() -> None:
    """Dynamic JSON maps must never become empty generic BaseModel instances."""
    adapter = TypeAdapter[Value](Value)
    expected: Value = {"nested": {"id": "example"}, "rows": [{"active": True}]}
    assert adapter.validate_python(expected) == expected
    assert adapter.validate_json('{"nested":{"id":"example"},"rows":[{"active":true}]}') == expected


def test_value_validation_preserves_native_model_identity() -> None:
    """A model branch accepts existing native instances without dictionary coercion."""
    patient = Patient(active=True)
    assert TypeAdapter[Value](Value).validate_python(patient) is patient


def test_value_serialization_preserves_native_model_fields() -> None:
    """Native model validation must retain polymorphic Pydantic serialization."""
    patient = Patient(active=True)
    adapter = TypeAdapter[Value](Value)
    payload = adapter.dump_json(patient)
    assert b'"active":true' in payload


class IterationGuardPatient(Patient):
    """A model that records unintended collection coercion at validation boundaries."""

    _iterated: bool = PrivateAttr(default=False)

    @property
    def iterated(self) -> bool:
        """Report whether a validator tried iterating the resource as a collection."""
        return self._iterated

    @override
    def __iter__(self) -> Generator[tuple[str, Value]]:
        """Reject collection coercion while permitting ordinary native model access."""
        self._iterated = True
        raise AssertionError("A native model must not be treated as a collection")


def test_native_value_never_attempts_collection_coercion() -> None:
    """Accepting native instances must not walk their data through rejected union arms."""
    patient = IterationGuardPatient(active=True)
    assert TypeAdapter[Value](Value).validate_python(patient) is patient
    assert evaluate(patient, "active") == [True]
    assert patient.iterated is False


def test_native_value_still_exposes_json_schema() -> None:
    """The native constraint must support schemas for public callback envelopes."""
    schema = TypeAdapter[Value](Value).json_schema()
    assert schema["$defs"]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("8.log({})", []),
        ("8.power({})", []),
        ("1.5.round({})", [Decimal(2)]),
        ("'abcdef'.substring(2, {})", ["cdef"]),
        ("'abcdef'.substring({})", []),
    ],
)
def test_empty_optional_arguments(expression: str, expected: Collection) -> None:
    """Optional empty arguments keep defaults; required empty arguments propagate."""
    assert evaluate(None, expression) == expected


class CountedModel(BaseModel):
    """A model whose validator exposes accidental revalidation of existing instances."""

    _validations: int = PrivateAttr(default=0)

    @property
    def validations(self) -> int:
        """Return the number of validation side effects on this instance."""
        return self._validations

    @model_validator(mode="after")
    def count_validation(self) -> Self:
        """Count the validation boundary so repeated validation is observable."""
        self._validations += 1
        return self


def test_native_constraint_respects_declared_model_class() -> None:
    """A native-only annotation accepts its exact model hierarchy without rerunning validators."""
    model = CountedModel()
    adapter = TypeAdapter[Annotated[CountedModel, NativeModel]](Annotated[CountedModel, NativeModel])
    assert adapter.validate_python(model) is model
    assert model.validations == 1
    with pytest.raises(ValidationError):
        adapter.validate_python(Patient(active=True))


@pytest.mark.parametrize("resource_type", [Patient, R4BPatient])
@pytest.mark.parametrize(
    "expression",
    [
        "name.given.first().length()",
        "name.given.first().toChars()",
        "name.given.first().substring(0, 1)",
        "name.given.first().upper()",
        "name.given.first().toString()",
        "name.given.first().convertsToString()",
        "name.given.first() < 'x'",
        "name.given.first() + 'x'",
        "multipleBirthInteger.abs()",
        "multipleBirthInteger + 1",
    ],
)
def test_extension_only_scalar_operations(resource_type: type[Patient] | type[R4BPatient], expression: str) -> None:
    """Primitive operations propagate absent scalar values while retaining elements."""
    patient = resource_type.model_validate(
        {
            "name": [{"_given": [{"extension": [{"url": "http://example.org/absent", "valueCode": "unknown"}]}]}],
            "_multipleBirthInteger": {"extension": [{"url": "http://example.org/absent", "valueCode": "unknown"}]},
        }
    )
    assert evaluate(patient, "name.given.exists()") == [True]
    assert evaluate(patient, "name.given.first().extension.value") == ["unknown"]
    assert evaluate(patient, expression) == []


@pytest.mark.parametrize("resource_type", [Patient, R4BPatient])
def test_join_skips_absent_primitive_values(resource_type: type[Patient] | type[R4BPatient]) -> None:
    """Extension-only primitive slots remain navigable but supply no joined text."""
    patient = resource_type.model_validate(
        {
            "name": [
                {
                    "given": ["a", None, "b"],
                    "_given": [
                        None,
                        {"extension": [{"url": "http://example.org/absent", "valueCode": "unknown"}]},
                        None,
                    ],
                }
            ]
        }
    )
    assert evaluate(patient, "name.given.join(',')") == ["a,b"]
    assert evaluate(patient, "name.given[1].join(',')") == []
    assert evaluate(patient, "name.given[1].extension.value") == ["unknown"]


@pytest.mark.parametrize("resource_type", [Patient, R4BPatient])
def test_native_nested_primitive_extensions(resource_type: type[Patient] | type[R4BPatient]) -> None:
    """Nested native extensions retain choice values and ids through primitive companions."""
    patient = resource_type.model_validate(
        {
            "active": True,
            "_active": {
                "id": "someid",
                "extension": [
                    {
                        "url": "http://example.org/outer",
                        "extension": [
                            {"id": "someid2", "url": "http://example.org/inner", "valueUri": "http://example.org/value"}
                        ],
                    }
                ],
            },
        }
    )
    assert evaluate(
        patient, "active.extension('http://example.org/outer').extension('http://example.org/inner').value"
    ) == ["http://example.org/value"]
    assert evaluate(
        patient, "active.extension('http://example.org/outer').extension('http://example.org/inner').id"
    ) == ["someid2"]
    assert evaluate(patient, "active.extension({})") == []
    assert evaluate(patient, "name.extension({})") == []


@pytest.mark.parametrize("value", [-2, 0, 1234567890123456789012345678901234567890])
def test_absolute_integer_preserves_native_type(value: int) -> None:
    """Integer math remains usable with a strict integer result adapter."""
    query = compile("abs()", output_type=int)
    assert query(value) == [abs(value)]
    assert evaluate(value, "abs().is(Integer)") == [True]


def test_decimal_absolute_preserves_all_digits() -> None:
    """Absolute value does not round a native Decimal to the active decimal context."""
    value = Decimal("-1234567890123456789012345678901234567890.123456789")
    assert compile("abs()", output_type=Decimal)(value) == [value.copy_abs()]


def test_decimal_round_preserves_integer_digits() -> None:
    """Rounding a long native Decimal keeps the integer part instead of returning empty."""
    value = Decimal("1234567890123456789012345678901234567890.123456789")
    assert compile("round(4)", output_type=Decimal)(value) == [Decimal("1234567890123456789012345678901234567890.1235")]


def test_coalesce_has_no_artificial_argument_ceiling() -> None:
    """The fluent form passes arbitrarily many native AST arguments without rendering text."""
    query = literal(None).call("coalesce", *(literal(None) for _ in range(101)), literal(7))
    assert evaluate(None, query) == [7]


def test_absolute_native_fhir_integer_has_strict_integer_output() -> None:
    """FHIR integer fields produce a System Integer when a numeric function creates a value."""
    patient = Patient.model_validate({"multipleBirthInteger": 2})
    assert compile("multipleBirthInteger.abs()", output_type=int)(patient) == [2]


def test_rounding_does_not_depend_on_or_mutate_ambient_precision() -> None:
    """A caller's Decimal context cannot silently erase digits during requested rounding."""
    value = Decimal("123456789012345678901234567890.5555")
    with localcontext() as context:
        context.prec = 6
        assert evaluate(value, "round(3)") == [Decimal("123456789012345678901234567890.556")]
        assert context.prec == 6


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("-$this", Decimal("-123456789012345678901234567890.123456789")),
        ("$this + 1", Decimal("123456789012345678901234567891.123456789")),
        ("$this - 1", Decimal("123456789012345678901234567889.123456789")),
        ("$this * 2", Decimal("246913578024691357802469135780.246913578")),
        ("$this / 2", Decimal("61728394506172839450617283945.0617283945")),
        ("$this mod 1", Decimal("0.123456789")),
    ],
)
def test_long_decimal_operations_are_lossless(expression: str, expected: Decimal) -> None:
    """Existing arithmetic operators handle long native Decimal values consistently."""
    value = Decimal("123456789012345678901234567890.123456789")
    assert compile(expression, output_type=Decimal)(value) == [expected]


def test_terminating_decimal_division_keeps_all_places() -> None:
    """A finite quotient is not rounded merely because its denominator has many digits."""
    denominator = Decimal(2**100)
    expected = Decimal(f"{5**100}e-100")
    assert compile("$this / %denominator", output_type=Decimal)(Decimal(1), {"denominator": denominator}) == [expected]


def test_fluent_native_date_arithmetic_never_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Native typed durations compose with FHIR fields without expression rendering."""
    patient = Patient.model_validate({"birthDate": "2018-02-01"})

    def reject_parse(expression: str) -> None:
        raise AssertionError("Fluent arithmetic must not parse query text")

    monkeypatch.setattr(query_module, "parse", reject_parse)
    expression = path("birthDate").binary("+", literal(QuantityValue(value=Decimal(1), unit="d")))
    assert compile(expression.eq(literal(date(2018, 2, 2))), output_type=bool)(patient) == [True]
    assert compile(literal(Decimal("7.5")).binary("/", literal(3)), output_type=Decimal)(None) == [Decimal("2.5")]
    assert compile(path("birthDate").binary("<=", literal(date(2018, 2, 2))), output_type=bool)(patient) == [True]
