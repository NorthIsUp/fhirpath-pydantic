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


def test_module_functions_are_thin_api_facades() -> None:
    """Runtime behavior belongs on owners; module functions only dispatch or delegate."""
    package = Path(__file__).parents[2] / "src" / "fhirpath_pydantic"
    violations: list[str] = []
    for path in package.glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(isinstance(decorator, ast.Name) and decorator.id == "overload" for decorator in node.decorator_list):
                continue
            body = node.body[1:] if ast.get_docstring(node) is not None else node.body
            # The typed compile facade dispatches between result-adapter specializations.
            if any(not isinstance(statement, (ast.Return, ast.If)) for statement in body) or any(
                not isinstance(statement.value, (ast.Call, ast.Attribute))
                for statement in ast.walk(node)
                if isinstance(statement, ast.Return)
            ):
                violations.append(f"{path.name}:{node.lineno}: {node.name}")
    assert not violations, "Behavior must be delegated to a model owner:\n" + "\n".join(violations)
