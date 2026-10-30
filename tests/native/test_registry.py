"""Exercise the complete pinned baseline registry without importing untyped contracts."""

import ast
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import ClassVar, Self, override

import pytest
from conformance import ConformanceReport
from fhir.resources.patient import Patient
from pydantic import RootModel

from fhirpath_pydantic import QuantityValue, evaluate, query
from fhirpath_pydantic.engine import State
from fhirpath_pydantic.native import Item
from fhirpath_pydantic.syntax import Node


class BaselineRegistry(RootModel[frozenset[str]]):
    """Source-level registration names remain independent of native dispatch declarations."""

    OPERATORS: ClassVar[frozenset[str]] = frozenset(
        {"containsOp", "inOp", "isOp", "asOp", "mod", "div", "or", "and", "xor", "implies"}
    )

    @classmethod
    def from_source(cls, source: str) -> Self:
        """Read registry keys without executing or trusting untyped upstream values."""
        for node in ast.parse(source).body:
            if not isinstance(node, ast.Assign) or not any(
                isinstance(target, ast.Name) and target.id == "invocation_registry" for target in node.targets
            ):
                continue
            if not isinstance(node.value, ast.Dict):
                raise ValueError("The pinned registry must be a literal dictionary")
            names: set[str] = set()
            for key in node.value.keys:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    raise ValueError("Every pinned registration must have a literal name")
                names.add(key.value)
            return cls(frozenset(names))
        raise ValueError("No upstream invocation registry found")

    def functions(self) -> frozenset[str]:
        """Internal operator aliases are not callable FHIRPath function names."""
        return frozenset(name for name in self.root if name.isidentifier() and name not in self.OPERATORS)


class RecordingState(State):
    """Record functions only after their actual native invocation returns successfully."""

    returned: ClassVar[set[str]] = set()

    @override
    def invoke(self, name: str, args: tuple[Node, ...], focus: list[Item]) -> list[Item]:
        result = super().invoke(name, args, focus)
        self.returned.add(name)
        return result


def test_every_baseline_function_is_exercised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registration alone cannot satisfy the baseline function coverage contract."""
    registry = BaselineRegistry.from_source(files("fhirpathpy.engine.invocations").joinpath("__init__.py").read_text())
    assert len(registry.root) == 111
    assert len(registry.functions()) == 87
    RecordingState.returned.clear()
    monkeypatch.setattr(query, "State", RecordingState)
    root = Path(__file__).parents[2]
    report = ConformanceReport.from_directory(root / "tests/cases", root / "tests/resources")
    assert len(report.outcomes) == 1545
    patient = Patient.model_validate({"name": [{"given": ["a"]}, {"given": ["b"]}]})
    assert patient.name is not None
    excluded = evaluate(patient, "name.exclude(name.first())")
    assert len(excluded) == 1 and excluded[0] is patient.name[1]
    assert registry.functions() <= RecordingState.returned, sorted(registry.functions() - RecordingState.returned)


class BaselineUnits(RootModel[dict[str, frozenset[str]]]):
    """Every conversion family comes from the pinned upstream implementation."""

    GROUPS: ClassVar[frozenset[str]] = frozenset(
        {
            "_year_month_conversion_factor",
            "_m_cm_mm_conversion_factor",
            "_lbs_kg_conversion_factor",
            "_g_mg_conversion_factor",
            "datetime_multipliers",
        }
    )

    @classmethod
    def from_source(cls, source: str) -> Self:
        """Read all upstream conversion keys, including calendar comprehension aliases."""
        families: dict[str, frozenset[str]] = {}
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in cls.GROUPS:
                    families[target.id] = cls.table_units(node.value)
        if frozenset(families) != cls.GROUPS:
            raise ValueError("The pinned unit conversion families changed")
        return cls(families)

    @classmethod
    def table_units(cls, table: ast.Dict) -> frozenset[str]:
        """Parse literal unit keys without evaluating any upstream Python code."""
        units: set[str] = set()
        for key, value in zip(table.keys, table.values, strict=True):
            if key is not None:
                candidates = [key]
            elif isinstance(value, ast.DictComp) and len(value.generators) == 1:
                sequence = value.generators[0].iter
                if not isinstance(sequence, ast.List):
                    raise ValueError("Unit aliases must remain a literal list")
                candidates = sequence.elts
            else:
                raise ValueError("Unexpected upstream unit table format")
            for candidate in candidates:
                if not isinstance(candidate, ast.Constant) or not isinstance(candidate.value, str):
                    raise ValueError("Unit names must be literal strings")
                units.add(candidate.value.strip("'"))
        if not units:
            raise ValueError("A conversion family cannot be empty")
        return frozenset(units)


def test_every_baseline_unit_conversion_pair() -> None:
    """All baseline conversion pairs are available and round-trip at native value precision."""
    catalogue = BaselineUnits.from_source(files("fhirpathpy.engine").joinpath("nodes.py").read_text())
    for family in catalogue.root.values():
        for source in family:
            quantity = QuantityValue(value=Decimal("1.2345"), unit=source)
            for target in family:
                converted = quantity.convert_to(target)
                assert converted is not None, (source, target)
                restored = converted.convert_to(source)
                assert restored is not None and quantity.equivalent(restored), (source, target)
