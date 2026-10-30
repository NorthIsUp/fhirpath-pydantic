"""Keep the parity audit honest about errors, validation, and exclusions."""

from pathlib import Path

import pytest
from conformance import CaseOutcome, ConformanceReport, FixtureCase, FixtureInput, FixtureNode, FixtureSuite
from pydantic import BaseModel

from fhirpath_pydantic import evaluate


@pytest.mark.parametrize(
    ("expression", "expected_status"),
    [
        ("(1 | 2).single()", "passed"),
        ("1", "failed"),
        ("1.unimplemented()", "unsupported"),
    ],
)
def test_expected_errors_execute_expression(expression: str, expected_status: str, tmp_path: Path) -> None:
    """An error marker cannot turn an unimplemented or successful expression green."""
    case = FixtureCase(expression=expression, error=True)
    status, _ = case.run(expression, None, tmp_path)
    assert status == expected_status


def test_native_input_rejection_is_not_expected_error(tmp_path: Path) -> None:
    """Malformed resource data cannot satisfy an assertion about interpreter errors."""
    case = FixtureCase(expression="id", error=True)
    status, _ = case.run("id", {"resourceType": "Observation"}, tmp_path)
    assert status == "input_rejected"


def test_groups_preserve_subject_disable_and_expression_lists() -> None:
    """Expansion retains every scenario and its inherited input and exclusion."""
    node = FixtureNode.model_validate(
        {
            "disable": True,
            "subject": {"id": "synthetic"},
            "group nested": [{"expression": ["id", "id.exists()"], "result": []}],
        }
    )
    [(case, subject)] = list(node.cases(None))
    assert case.disable is True
    assert case.expressions() == ("id", "id.exists()")
    assert subject == {"id": "synthetic"}


def test_all_disabled_is_not_complete() -> None:
    """An empty or entirely disabled run proves no feature parity."""
    assert ConformanceReport().complete() is False
    report = ConformanceReport(
        outcomes=[CaseOutcome(source="test.yaml", ordinal=1, expression="1", status="disabled", reason="Disabled")]
    )
    assert report.complete() is False


@pytest.mark.parametrize("status", ["failed", "unsupported", "input_rejected", "unexpected_error", "missing_expected"])
def test_any_unresolved_case_prevents_completion(status: str) -> None:
    """Every failure category remains visible in the parity gate."""
    report = ConformanceReport.model_validate(
        {
            "outcomes": [
                {"source": "test.yaml", "ordinal": 1, "expression": "1", "status": "passed", "reason": "Matched"},
                {"source": "test.yaml", "ordinal": 2, "expression": "2", "status": status, "reason": "Unresolved"},
            ]
        }
    )
    assert report.complete() is False


def test_standard_patient_fixture_is_native() -> None:
    """The audit must accept the original valid patient rather than corrupting its payload."""
    from_input = FixtureInput.from_file(Path(__file__).parents[1] / "resources" / "patient-example.json")
    assert isinstance(from_input.value, BaseModel)
    assert evaluate(from_input.value, "name.given") == ["Peter", "James", "Jim", "Peter", "James"]


def test_generic_subject_fields_survive_validation() -> None:
    """A valid group subject cannot silently disappear during YAML boundary validation."""
    suite = FixtureSuite.from_file(Path(__file__).parents[1] / "cases" / "5.1_existence.yaml")
    assert evaluate(suite.subject, "Functions.attrsingle") == [1]


def test_legacy_error_result_is_executed_as_error_assertion(tmp_path: Path) -> None:
    """Legacy status-error objects describe an exception, not a returned value."""
    case = FixtureCase.model_validate(
        {"expression": "(1 | 2).single()", "result": [{"$status": "error", "$error": "Expected single"}]}
    )
    assert case.run("(1 | 2).single()", None, tmp_path)[0] == "passed"
