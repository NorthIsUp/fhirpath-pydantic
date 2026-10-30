"""Exercise the complete pinned baseline registry without importing untyped contracts."""

import ast
from importlib.resources import files
from pathlib import Path
from typing import ClassVar, Self, override

import pytest
from conformance import ConformanceReport
from fhir.resources.patient import Patient
from pydantic import RootModel

from fhirpath_pydantic import evaluate, query
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
