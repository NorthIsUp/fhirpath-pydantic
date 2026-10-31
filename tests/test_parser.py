"""Typed historical regression cases for the pinned fhirpathpy baseline."""

import json
from pathlib import Path

import pytest
from antlr4.error.Errors import LexerNoViableAltException
from fhirpathpy.parser import parse
from pydantic import TypeAdapter

from fhirpath_pydantic.types import Value

ast_fixtures_path = Path(__file__).resolve().parent.joinpath("fixtures").joinpath("ast")


def load_ast_fixture(fixture_name: str) -> dict[str, Value]:
    """Validate a stored parser tree before comparing its fields."""
    fixture_path = ast_fixtures_path.joinpath(fixture_name + ".json")
    return TypeAdapter(dict[str, Value]).validate_json(fixture_path.read_bytes())


def are_ast_equal(first_ast: dict[str, Value], second_ast: dict[str, Value]) -> bool:
    """Compare parser trees independently of mapping key order."""
    first_string = json.dumps(first_ast, sort_keys=True)
    second_string = json.dumps(second_ast, sort_keys=True)

    return first_string == second_string


@pytest.mark.parametrize(
    "expression",
    [
        "4+4",
        "object",
        "object.method()",
        "object.method(42)",
        "object.property",
        "object.property.method()",
        "object.property.method(42)",
    ],
)
def parse_valid_test(expression: str) -> None:
    """Valid expressions produce a nonempty parser tree."""
    assert parse(expression) != {}


def parse_non_valid_test() -> None:
    """An invalid token raises the lexer error."""
    with pytest.raises(LexerNoViableAltException):
        parse("!")


@pytest.mark.parametrize(
    "expression",
    [
        "%v+2",
        "a.b+2",
        "Observation.value",
        "Patient.name.given",
    ],
)
def output_correct_ast_test(expression: str) -> None:
    """Parsed trees match the stored grammar fixtures."""
    assert are_ast_equal(parse(expression), load_ast_fixture(expression))
