"""Escaped names use the same FHIRPath decoding as string literals."""

import pytest
from fhir.resources.patient import Patient

from fhirpath_pydantic import FHIRPathError, compile, evaluate


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


@pytest.mark.parametrize("expression", [r"'\u+041'", r"'\u123'", r"%'\u+041'", r"1 '\u+041'"])
def test_invalid_unicode_rejected_during_compilation(expression: str) -> None:
    """Malformed Unicode escapes fail at the syntax boundary even in unevaluated branches."""
    with pytest.raises(FHIRPathError, match="Unicode"):
        compile(expression)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [(r"'\\u+041'", r"\u+041"), (r"'\u0041'", "A"), (r"'\q'", "q")],
)
def test_literal_escape_decoding(expression: str, expected: str) -> None:
    """Escaped backslashes are literal and unknown escapes retain their character."""
    assert evaluate(None, expression) == [expected]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("(1 | 1 is Integer).count()", [2]),
        ("(1 | 2 as Integer).count()", [2]),
        ("1 + 2 is Integer", [True]),
        ("(1 > 2) is Boolean", [True]),
    ],
)
def test_type_operator_precedence(expression: str, expected: list[int | bool]) -> None:
    """Type operators bind after arithmetic and before union or comparison."""
    assert evaluate(None, expression) == expected


def test_comparison_does_not_bind_before_type_operator() -> None:
    """Unparenthesized type tests do not turn the entire comparison into a Boolean test."""
    with pytest.raises(FHIRPathError):
        evaluate(None, "1 > 2 is Boolean")
