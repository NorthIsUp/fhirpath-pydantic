"""Escaped names use the same FHIRPath decoding as string literals."""

import pytest
from fhir.resources.patient import Patient

from fhirpath_pydantic import evaluate


@pytest.mark.parametrize(
    "expression",
    [r"Patient.`\u006eame`.given.first()", r"Patient.name.`\u0067iven`.first()"],
)
def test_escaped_native_member(expression: str) -> None:
    """Unicode escapes resolve native fields without serializing the resource."""
    patient = Patient.model_validate({"name": [{"given": ["Ada"]}]})
    assert evaluate(patient, expression) == ["Ada"]


@pytest.mark.parametrize("expression", [r"%`\u006eame`", r"%'\u006eame'"])
def test_escaped_variable(expression: str) -> None:
    """Quoted environment names decode before looking up typed caller values."""
    assert evaluate(None, expression, {"name": "Ada"}) == ["Ada"]


def test_escaped_function_and_type() -> None:
    """Delimited function and qualified type identifiers decode consistently."""
    assert evaluate(None, r"'Ada'.`\u006cength`()") == [3]
    assert evaluate(None, r"1 is `\u0053ystem`.`\u0049nteger`") == [True]
    assert evaluate(None, r"1.ofType(`\u0053ystem`.`\u0049nteger`)") == [1]
