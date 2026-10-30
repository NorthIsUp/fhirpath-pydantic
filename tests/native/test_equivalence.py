"""Equivalence respects decimal precision without weakening exact equality."""

from decimal import Decimal
from typing import Never

import pytest
from fhir.resources.humanname import HumanName

from fhirpath_pydantic import evaluate, literal
from fhirpath_pydantic.types import Value


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1.001 ~ 1.0012", True),
        ("1.100 ~ 1.101", True),
        ("1.1 ~ 1.0", True),
        ("1.10 ~ 1.00", True),
        ("1.1 ~ 1.2", False),
        ("11 ~ 10", False),
        ("0.00000011 ~ 0.00000010", True),
        ("0 ~ 0.00000010", True),
        ("1 ~ 0.00000010", False),
        ("1.001 !~ 1.0012", False),
        ("1.001 = 1.0012", False),
        ("true ~ 1.0", False),
    ],
)
def test_decimal_equivalence(expression: str, expected: bool) -> None:
    """Only equivalence rounds both decimal operands to the least precision."""
    assert evaluate(None, expression) == [expected]


def test_large_decimal_equivalence_preserves_all_digits() -> None:
    """Decimal normalization must not silently round at the process context precision."""
    left = Decimal("123456789012345678901234567890.001")
    right = Decimal("123456789012345678901234567890.0012")
    expression = literal(left).call("combine", literal(right))
    assert evaluate(None, expression) == [left, right]
    assert evaluate(None, "(%a ~ %b)", {"a": left, "b": right}) == [True]
    assert evaluate(None, "(%a = %b)", {"a": left, "b": right}) == [False]


def test_nested_equivalence_is_recursive_and_unordered() -> None:
    """Complex values normalize text and compare nested collections recursively."""
    left: Value = {"label": "Ab  C", "values": [{"number": 1}, {"number": 2}]}
    right: Value = {"label": "ab c", "values": [{"number": 2}, {"number": Decimal("1.1")}]}
    assert evaluate(None, "%a ~ %b", {"a": left, "b": right}) == [True]
    assert evaluate(None, "%a = %b", {"a": left, "b": right}) == [False]


def test_native_fhir_equivalence_uses_fields_without_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    """Native model equivalence ignores FHIR element ids and compares real values."""
    left = HumanName.model_validate({"id": "left", "given": ["Ada", "Grace"]})
    right = HumanName.model_validate({"id": "right", "given": ["grace", "ADA"]})
    monkeypatch.setattr(HumanName, "model_dump", DumpGuard.reject)
    assert evaluate(None, "%a ~ %b", {"a": left, "b": right}) == [True]
    assert evaluate(None, "%a = %b", {"a": left, "b": right}) == [False]


class DumpGuard:
    """A serialization boundary deliberately unavailable to native comparison."""

    @staticmethod
    def reject() -> Never:
        """Fail if comparison attempts to serialize a native model."""
        raise AssertionError("Native comparison must not dump models")
