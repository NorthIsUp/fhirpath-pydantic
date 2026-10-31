"""Typed historical regression cases for the pinned fhirpathpy baseline."""

import copy

import pytest
from fhirpathpy import evaluate
from fhirpathpy.models import models

from fhirpath_pydantic.types import Value
from tests.resources import resources


@pytest.mark.parametrize(
    ("resource", "path"),
    [
        (
            {
                "resourceType": "Patient",
                "name": [{"given": ["First", "Middle"], "family": "Last"}],
            },
            "Patient.name.given.toDate()",
        ),
    ],
)
def path_functions_test(resource: dict[str, Value], path: str) -> None:
    """Traversal retains the declared results and cardinality."""
    with pytest.raises(Exception) as e:
        evaluate(resource, path)
    assert str(e.value) == "to_date called for a collection of length 2"


def evaluate_does_not_mutate_float_values_test() -> None:
    """evaluate() must not convert floats to Decimal in the caller's dict."""
    quantity: dict[str, float | str] = {
        "value": 37.2,
        "unit": "°C",
        "system": "http://unitsofmeasure.org",
        "code": "Cel",
    }
    qr = {
        "resourceType": "QuestionnaireResponse",
        "status": "completed",
        "item": [
            {
                "linkId": "temperature",
                "answer": [{"valueQuantity": quantity}],
            }
        ],
    }
    evaluate(qr, "QuestionnaireResponse.repeat(item).answer")
    assert isinstance(quantity["value"], float)


def copy_deepcopy_test() -> None:
    """Shallow and deep copies retain partial date values."""
    copy_1 = copy.copy(evaluate({}, "@2018"))
    copy_2 = evaluate({}, "@2018").copy()

    deepcopy_1 = copy.deepcopy(evaluate({}, "@2018"))

    assert copy_1[0] == "2018"
    assert copy_2[0] == "2018"
    assert deepcopy_1[0] == "2018"


def to_quantity_with_comparator_test() -> None:
    """Quantity conversion rejects an inexact comparator."""
    resource = resources["quantity-example.json"]
    expression = "QuestionnaireResponse.item[3].answer.value.toQuantity()"
    with pytest.raises(ValueError, match="Cannot convert a FHIR.Quantity"):
        evaluate(resource, expression, {}, models["r4"])
