"""Quantity behavior uses native Pydantic values instead of legacy wrappers."""

from decimal import Decimal

import pytest
from fhir.resources.observation import Observation
from fhir.resources.quantity import Quantity
from fhir.resources.R4B.quantity import Quantity as R4BQuantity
from pydantic import ValidationError

from fhirpath_pydantic import FHIRPathError, compile, evaluate
from fhirpath_pydantic.quantities import QuantityValue
from fhirpath_pydantic.types import Collection


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("(2 'mo').value", [Decimal(2)]),
        ("(2 years).unit", ["year"]),
        ("1 'g' = 1000 'mg'", [True]),
        ("1 'kg' = 1000 'g'", [True]),
        ("1 'cm' = 10 'mm'", [True]),
        ("1 'g' = 1 'm'", []),
        ("1 year = 12 months", [True]),
        ("1 year = 1 'a'", [False]),
        ("1 year ~ 1 'a'", [True]),
        ("1 year > 1 'a'", []),
        ("1 second = 1 's'", [True]),
        ("1 'kg' > 900 'g'", [True]),
        ("(1 'cm').toQuantity('mm').value", [Decimal(10)]),
        ("(1 'cm').toQuantity('g')", []),
        ("(1 year).toQuantity('months').value", [Decimal(12)]),
        ("(1 year).toQuantity('days').value", [Decimal(365)]),
        ("'1 day'.toQuantity() = 1 day", [True]),
        ("'invalid'.toQuantity()", []),
        ("false.toQuantity().value", [Decimal(0)]),
        ("1.toQuantity().unit", ["1"]),
        ("{}.toQuantity()", []),
        ("'invalid'.convertsToQuantity()", [False]),
        ("(1 'cm').convertsToQuantity('mm')", [True]),
        ("(1 'cm').convertsToQuantity('g')", [False]),
        ("(3 'm' + 3 'cm').value", [Decimal(303)]),
        ("(3 'm' + 3 'cm').unit", ["cm"]),
        ("(3 'm' - 3 'cm').value", [Decimal(297)]),
        ("(2 'cm' * 3 'cm').unit", ["cm2"]),
        ("(2 'cm' * 3 'cm').value", [Decimal(6)]),
        ("(12 'cm2' / 3 'cm').unit", ["cm"]),
        ("(12 'cm2' / 3 'cm').value", [Decimal(4)]),
        ("(2 'cm' * 3).value", [Decimal(6)]),
        ("(12 'cm' / 3).value", [Decimal(4)]),
        ("(12 'cm' / 0)", []),
        ("(3 'm' + 1 's')", []),
        ("(1 'm' | 100 'cm').count()", [1]),
        ("(1 'g').toString()", ["1 'g'"]),
        ("(1 'g') is System.Quantity", [True]),
        ("(1 'g') is FHIR.Quantity", [False]),
    ],
)
def test_quantity_semantics(expression: str, expected: Collection) -> None:
    """Quantities respect dimensions, calendar semantics, and conversion units."""
    assert evaluate(None, expression) == expected


@pytest.mark.parametrize("model", [Quantity, R4BQuantity])
def test_native_quantity_conversion(model: type[Quantity] | type[R4BQuantity]) -> None:
    """Both FHIR releases convert directly while preserving the source instance."""
    resource = model.model_validate({"value": Decimal("0.25"), "system": "http://unitsofmeasure.org", "code": "kg"})
    assert evaluate(resource, "$this")[0] is resource
    assert evaluate(resource, "$this.toQuantity('g').value") == [Decimal(250)]
    assert evaluate(resource, "$this = 250 'g'") == [True]


def test_native_choice_quantity() -> None:
    """Quantity choices participate in comparisons without dumping the Observation."""
    resource = Observation.model_validate(
        {
            "status": "final",
            "code": {"text": "quantity"},
            "valueQuantity": {"value": 2, "system": "http://unitsofmeasure.org", "code": "a"},
        }
    )
    assert evaluate(resource, "value")[0] is resource.valueQuantity
    assert evaluate(resource, "value = 2 years") == [True]
    assert evaluate(resource, "value ~ 2 'a'") == [True]


def test_comparator_is_not_an_exact_quantity() -> None:
    """A native comparator remains navigable but cannot silently become exact."""
    resource = Quantity.model_validate(
        {"value": 2, "system": "http://unitsofmeasure.org", "code": "mg", "comparator": ">"}
    )
    assert evaluate(resource, "comparator") == [">"]
    with pytest.raises(FHIRPathError, match="comparator"):
        evaluate(resource, "$this.toQuantity()")


def test_foreign_unit_system_is_not_ucum() -> None:
    """An unrelated code system must never be silently interpreted as UCUM."""
    resource = Quantity.model_validate({"value": 2, "system": "http://example.org/units", "code": "mg"})
    assert evaluate(resource, "$this.toQuantity()") == []


def test_conversion_rejects_multiple_quantities() -> None:
    """Quantity conversion is a singleton operation with checked cardinality."""
    with pytest.raises(FHIRPathError, match="singleton"):
        evaluate(None, "(1 | 2).toQuantity()")


def test_quantity_model_validation() -> None:
    """The quantity boundary validates JSON-like inputs and rejects nonfinite values."""
    model = QuantityValue.model_validate({"value": "1.25", "unit": "grams"})
    assert model.value == Decimal("1.25")
    with pytest.raises(ValidationError):
        QuantityValue.model_validate({"value": "NaN", "unit": "g"})
    with pytest.raises(ValidationError):
        QuantityValue.model_validate({"value": 1, "unit": ""})


def test_quantity_model_arithmetic() -> None:
    """Unit-aware model methods retain precision without an evaluator round trip."""
    left = QuantityValue.model_validate({"value": 1, "unit": "m"})
    right = QuantityValue.model_validate({"value": 1, "unit": "cm"})
    result = left.arithmetic("+", right)
    assert result is not None
    assert result.value == Decimal(101)
    assert result.unit == "cm"
    assert left.value == Decimal(1)


def test_typed_quantity_result() -> None:
    """Compiled result validation returns a typed Pydantic System.Quantity."""
    query = compile("1 'cm'", output_type=QuantityValue)
    result = query(None)
    assert result[0].value == Decimal(1)
    assert result[0].unit == "cm"
    assert QuantityValue.model_validate_json(result[0].model_dump_json()) == result[0]


def test_decimal_unit_conversion_is_not_rounded_to_an_integer() -> None:
    """Unlike upstream's legacy conversion, nonintegral masses retain precision."""
    assert evaluate(None, "(1.5 'g').toQuantity('mg').value") == [Decimal(1500)]
    assert evaluate(None, "(185 '[lb_av]').toQuantity('kg').value") == [Decimal("83.91458845")]


def test_compound_units_and_case_sensitivity() -> None:
    """Compound dimensions convert consistently and UCUM unit case is significant."""
    assert evaluate(None, "1 'mg/dL' = 10 'mg/L'") == [True]
    assert evaluate(None, "1 'kg' = 1 'KG'") == []
    assert evaluate(None, "(1 'kg').toQuantity('unknown-unit')") == []


def test_quantity_arithmetic_retains_source_models() -> None:
    """Arithmetic converts values without replacing the caller's FHIR model."""
    resource = Quantity.model_validate({"value": 1, "system": "http://unitsofmeasure.org", "code": "kg"})
    assert evaluate(resource, "$this + 500 'g'") == [QuantityValue(value=Decimal(1500), unit="g")]
    assert evaluate(resource, "$this")[0] is resource
    assert resource.value == Decimal(1)
