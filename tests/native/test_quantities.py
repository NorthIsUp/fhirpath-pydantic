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
        ("1 year < 2 months", [False]),
        ("1 year > 2 months", [True]),
        ("1 year <= 2 days", [False]),
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


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("4 'g' ~ 4040 'mg'", [True]),
        ("4040 'mg' ~ 4 'g'", [True]),
        ("4.01 'g' ~ 4040 'mg'", [False]),
        ("185 '[lb_av]' ~ 84 'kg'", [True]),
        ("84 'kg' ~ 185 '[lb_av]'", [True]),
        ("1 'kg' ~ 1 'm'", [False]),
        ("4 'g' = 4040 'mg'", [False]),
    ],
)
def test_quantity_equivalence_preserves_source_precision(expression: str, expected: Collection) -> None:
    """Unit conversion shifts comparison precision without rounding actual values."""
    assert evaluate(None, expression) == expected
    assert evaluate(None, "(185 '[lb_av]').toQuantity('kg').value") == [Decimal("83.91458845")]


@pytest.mark.parametrize("quantity_type", [Quantity, R4BQuantity])
def test_native_quantity_absolute(quantity_type: type[Quantity] | type[R4BQuantity]) -> None:
    """The numeric function maps UCUM-coded native quantities without altering the input."""
    quantity = quantity_type.model_validate(
        {"value": Decimal("-5.500"), "system": "http://unitsofmeasure.org", "code": "mg"}
    )
    assert evaluate(quantity, "abs()") == [QuantityValue(value=Decimal("5.500"), unit="mg")]
    assert quantity.value == Decimal("-5.500")


@pytest.mark.parametrize("value", ["-5.500", "0", "5.500", "-1234567890123456789012345678901234567890.123"])
def test_system_quantity_absolute(value: str) -> None:
    """Absolute values retain unit and exact Decimal digits beyond context precision."""
    quantity = QuantityValue(value=Decimal(value), unit="mg")
    assert evaluate(quantity, "abs()") == [QuantityValue(value=Decimal(value).copy_abs(), unit="mg")]


@pytest.mark.parametrize("quantity_type", [Quantity, R4BQuantity])
@pytest.mark.parametrize("unit", [None, "tablets", "mg/dL"])
def test_native_uncoded_quantity_comparison(
    quantity_type: type[Quantity] | type[R4BQuantity], unit: str | None
) -> None:
    """Native quantities with matching unit text compare without becoming UCUM quantities."""
    left = quantity_type.model_validate({"value": Decimal("1.20"), "unit": unit})
    right = quantity_type.model_validate({"value": Decimal("1.20"), "unit": unit})
    higher = quantity_type.model_validate({"value": Decimal("2.40"), "unit": unit})
    assert evaluate(left, "$this = %right", {"right": right}) == [True]
    assert evaluate(left, "$this ~ %right", {"right": right}) == [True]
    assert evaluate(left, "$this < %right", {"right": higher}) == [True]
    assert evaluate(left, "$this >= %right", {"right": higher}) == [False]
    assert evaluate(left, "toQuantity()") == []
    assert left.value == Decimal("1.20")


@pytest.mark.parametrize("quantity_type", [Quantity, R4BQuantity])
def test_native_unit_text_and_coded_quantity_comparison(quantity_type: type[Quantity] | type[R4BQuantity]) -> None:
    """An uncoded unit matches a coded quantity's display text without unit conversion."""
    left = quantity_type.model_validate({"value": 1, "unit": "mg/dL"})
    right = quantity_type.model_validate(
        {"value": 2, "unit": "mg/dL", "system": "http://unitsofmeasure.org", "code": "mg/dL"}
    )
    assert evaluate(left, "$this < %right", {"right": right}) == [True]
    assert evaluate(right, "$this > %left", {"left": left}) == [True]


@pytest.mark.parametrize("quantity_type", [Quantity, R4BQuantity])
def test_native_incompatible_unit_text_is_indeterminate(quantity_type: type[Quantity] | type[R4BQuantity]) -> None:
    """Different or missing unit text cannot be guessed or converted from display labels."""
    left = quantity_type.model_validate({"value": 1, "unit": "tablets"})
    for unit in (None, "Tablets", "capsules"):
        right = quantity_type.model_validate({"value": 1, "unit": unit})
        assert evaluate(left, "$this = %right", {"right": right}) == []
        assert evaluate(left, "$this ~ %right", {"right": right}) == [False]
        assert evaluate(left, "$this < %right", {"right": right}) == []


@pytest.mark.parametrize("quantity_type", [Quantity, R4BQuantity])
def test_uncoded_comparators_cannot_be_compared_as_exact(quantity_type: type[Quantity] | type[R4BQuantity]) -> None:
    """Comparison does not drop a comparator merely because UCUM conversion is unavailable."""
    left = quantity_type.model_validate({"value": 1, "unit": "tablets", "comparator": ">"})
    right = quantity_type.model_validate({"value": 2, "unit": "tablets"})
    with pytest.raises(FHIRPathError, match="comparator"):
        evaluate(left, "$this < %right", {"right": right})


@pytest.mark.parametrize("quantity_type", [Quantity, R4BQuantity])
def test_missing_display_unit_is_not_dimensionless(quantity_type: type[Quantity] | type[R4BQuantity]) -> None:
    """A coded magnitude cannot match a unitless quantity because both lack display text."""
    left = quantity_type.model_validate({"value": 1})
    right = quantity_type.model_validate({"value": 1, "system": "http://unitsofmeasure.org", "code": "mg"})
    assert evaluate(left, "$this = %right", {"right": right}) == []
    assert evaluate(left, "$this ~ %right", {"right": right}) == [False]
    assert evaluate(left, "$this < %right", {"right": right}) == []


@pytest.mark.parametrize("quantity_type", [Quantity, R4BQuantity])
def test_native_quantity_missing_magnitude_is_indeterminate(quantity_type: type[Quantity] | type[R4BQuantity]) -> None:
    """Unit text does not invent a numeric value for an incomplete native quantity."""
    left = quantity_type.model_validate({"unit": "tablets"})
    right = quantity_type.model_validate({"value": 1, "unit": "tablets"})
    assert evaluate(left, "$this = %right", {"right": right}) == []
    assert evaluate(left, "$this ~ %right", {"right": right}) == [False]
    assert evaluate(left, "$this < %right", {"right": right}) == []


def test_large_quantity_conversion_preserves_digits() -> None:
    """A finite unit scaling must not round a native magnitude at 28 digits."""
    quantity = QuantityValue(value=Decimal("123456789012345678901234567890.123456789"), unit="g")
    assert evaluate(quantity, "toQuantity('mg').value") == [Decimal("123456789012345678901234567890123.456789")]


def test_large_quantity_negation_preserves_digits() -> None:
    """Unary quantity operations preserve the full native Decimal magnitude."""
    quantity = QuantityValue(value=Decimal("123456789012345678901234567890.123456789"), unit="g")
    assert evaluate(quantity, "-$this") == [QuantityValue(value=quantity.value.copy_negate(), unit="g")]


def test_large_quantity_string_preserves_digits() -> None:
    """Rendering a typed quantity cannot change its numeric value."""
    quantity = QuantityValue(value=Decimal("123456789012345678901234567890.12345678900"), unit="g")
    assert evaluate(quantity, "toString()") == ["123456789012345678901234567890.123456789 'g'"]


def test_large_quantity_arithmetic_preserves_digits() -> None:
    """Dimensional arithmetic retains long magnitudes rather than silently rounding them."""
    quantity = QuantityValue(value=Decimal("123456789012345678901234567890.123456789"), unit="g")
    assert evaluate(quantity, "$this + 1 'g'") == [
        QuantityValue(value=Decimal("123456789012345678901234567891.123456789"), unit="g")
    ]
    assert evaluate(quantity, "$this * 2") == [
        QuantityValue(value=Decimal("246913578024691357802469135780.246913578"), unit="g")
    ]
