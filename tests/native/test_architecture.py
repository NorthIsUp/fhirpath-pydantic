"""Architectural contracts for the typed Pydantic implementation."""

import ast
from pathlib import Path


def test_private_behavior_belongs_to_models() -> None:
    """Private module-level functions cannot accumulate outside model owners."""
    package = Path(__file__).parents[2] / "src" / "fhirpath_pydantic"
    violations: list[str] = []
    for path in package.glob("*.py"):
        module = ast.parse(path.read_text())
        violations.extend(
            f"{path.name}:{node.lineno}: {node.name}"
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_")
        )
    assert not violations, "Private behavior must have a model owner:\n" + "\n".join(violations)
