"""Function parity for collection aggregates and text utilities."""

from decimal import Decimal

import pytest
from fhir.resources.observation import Observation

from fhirpath_pydantic import FHIRPathError, QuantityValue, evaluate
from fhirpath_pydantic.types import Collection


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("(1 | 2 | 3).sum()", [6]),
        ("(1 | 2 | 3).avg()", [Decimal(2)]),
        ("(1 | 2 | 3).min()", [1]),
        ("(1 | 2 | 3).max()", [3]),
        ("{}.sum()", [0]),
        ("{}.avg()", []),
        ("{}.min()", []),
        ("{}.max()", []),
        ("(1.1 | 2.2).sum()", [Decimal("3.3")]),
        ("(1.1 | 2.2).avg()", [Decimal("1.65")]),
        ("(1 'kg' | 500 'g').sum().value", [Decimal(1500)]),
        ("(1 'kg' | 500 'g').avg().value", [Decimal(750)]),
        ("(1 'kg' | 500 'g').min().value", [Decimal(500)]),
        ("(1 'kg' | 500 'g').max().value", [Decimal(1)]),
        ("'  text  '.trim()", ["text"]),
        ("''.trim()", [""]),
        ("{}.trim()", []),
        ("'hello'.encode('base64')", ["aGVsbG8="]),
        ("'aGVsbG8='.decode('base64')", ["hello"]),
        ("'hello'.encode('hex')", ["68656c6c6f"]),
        ("'68656c6c6f'.decode('hex')", ["hello"]),
        ("'Zoë'.encode('hex').decode('hex')", ["Zoë"]),
        ("'Zoë'.encode('base64').decode('base64')", ["Zoë"]),
        ("'hello'.encode('base64url').decode('urlbase64')", ["hello"]),
        ("'hello'.encode('unknown')", []),
        ("'hello'.decode('unknown')", []),
        ("{}.encode('base64')", []),
        ("{}.decode('base64')", []),
        ("'ab'.replaceMatches('(a)(b)', '$2$1')", ["ba"]),
        ("'a\\nb'.matches('a.b')", [True]),
    ],
)
def test_utility_functions(expression: str, expected: Collection) -> None:
    """Aggregate and text features retain native values and empty semantics."""
    assert evaluate(None, expression) == expected


@pytest.mark.parametrize(
    "expression",
    ["(1 | 'x').sum()", "true.avg()", "(1 | 2).encode('hex')", "'xx'.decode('hex')", "'!!!'.decode('base64')"],
)
def test_utility_contract_errors(expression: str) -> None:
    """Invalid scalar types, cardinality and encodings fail explicitly."""
    with pytest.raises(FHIRPathError):
        evaluate(None, expression)


def test_native_quantity_aggregate() -> None:
    """Aggregation converts native observations without mutating source quantities."""
    first = Observation.model_validate(
        {
            "status": "final",
            "code": {"text": "aggregate"},
            "valueQuantity": {"value": 1, "system": "http://unitsofmeasure.org", "code": "kg"},
        }
    )
    second = Observation.model_validate(
        {
            "status": "final",
            "code": {"text": "aggregate"},
            "valueQuantity": {"value": 500, "system": "http://unitsofmeasure.org", "code": "g"},
        }
    )
    assert evaluate([first, second], "value.sum()") == [QuantityValue(value=Decimal(1500), unit="g")]
    assert first.valueQuantity is not None
    assert first.valueQuantity.value == Decimal(1)
