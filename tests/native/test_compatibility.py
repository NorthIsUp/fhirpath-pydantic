"""Differential checks against the fork's fhirpathpy 2.2.4 baseline."""

import pytest
from fhir.resources.patient import Patient
from fhirpathpy import evaluate as upstream_evaluate
from pydantic import TypeAdapter

from fhirpath_pydantic import FHIRPathError, UnsupportedFeatureError, compile_as_array, compile_as_first, evaluate, path
from fhirpath_pydantic.types import Collection, Value

_PAYLOAD = TypeAdapter[dict[str, Value]](dict[str, Value])


@pytest.mark.parametrize(
    "expression",
    [
        "Patient.name.given",
        "name.first().given",
        "name.last().given",
        "name.tail().given",
        "name.skip(1).given",
        "name.take(1).given",
        "name.where(use = 'official').given",
        "name.select(given)",
        "name.exists(use = 'official')",
        "name.all(given.exists())",
        "name.count()",
        "name.empty()",
        "active.not()",
        "name.given.distinct()",
        "name.given.isDistinct()",
        "(1 | 2).intersect(2 | 3)",
        "(1 | 2).exclude(2)",
        "(1 | 2).subsetOf(1 | 2 | 3)",
        "(1 | 2 | 3).supersetOf(1 | 2)",
        "(1 | 2).union(2 | 3)",
        "(1 | 2).combine(2 | 3)",
        "'abc'.startsWith('a')",
        "'abc'.endsWith('c')",
        "'abc'.contains('b')",
        "'abc'.indexOf('b')",
        "'abc'.length()",
        "'ABC'.lower()",
        "'abc'.upper()",
        "'a,b'.split(',')",
        "'abc'.replace('b', 'x')",
        "'abc'.matches('^a')",
        "'abc'.substring(1)",
        "'abc'.toChars()",
        "'ab'.replaceMatches('a', 'x')",
        "'12'.toInteger()",
        "'12.5'.toDecimal()",
        "'yes'.toBoolean()",
        "'invalid'.toInteger()",
        "(-2).abs()",
        "1.5.ceiling()",
        "1.5.floor()",
        "1.5.truncate()",
        "4.sqrt()",
        "2.power(3)",
        "(true | false).allTrue()",
        "(true | false).anyTrue()",
        "(true | false).allFalse()",
        "(true | false).anyFalse()",
        "true and false",
        "false or true",
        "true xor true",
        "false implies false",
        "{} and false",
        "{} or true",
        "{} ~ {}",
        "1 in (1 | 2)",
        "(1 | 2) contains 2",
        "2 >= 1",
        "1 <= 2",
        "1 != 2",
        "'abc' ~ 'ABC'",
        "2 + 3",
        "2 - 3",
        "2 * 3",
        "5 div 2",
        "5 mod 2",
        "'a' & 'b'",
        "iif(true, 1, 2)",
        "name.given[0]",
        "name.given[99]",
        "name.given[-1]",
        "(1 | 2).select($index)",
    ],
)
def test_upstream_semantics(expression: str) -> None:
    """The native model and upstream JSON engine agree on shared functionality."""
    # Literal values exercise exact filtering and Unicode results.
    resource = Patient.model_validate(
        {"active": True, "name": [{"use": "official", "given": ["Zoë", "Ada"]}, {"use": "usual", "given": ["Z"]}]}
    )
    payload = _PAYLOAD.validate_python(resource.model_dump(by_alias=True, exclude_none=True))
    assert evaluate(resource, expression) == upstream_evaluate(payload, expression)


def test_compatibility_helpers() -> None:
    """Typed compatibility helpers check input and handle missing results."""
    resource = Patient.model_validate({"active": True})
    assert compile_as_array("active", Patient, bool)(resource) == [True]
    assert compile_as_first("active", Patient, bool)(resource) is True
    assert compile_as_first("name", Patient, str)(resource) is None


@pytest.mark.parametrize("expression", ["@2020", "$this.type()"])
def test_unsupported_features(expression: str) -> None:
    """Features outside the supported subset never silently coerce or serialize."""
    with pytest.raises(UnsupportedFeatureError):
        evaluate(None, expression)


def test_native_input_unchanged() -> None:
    """Traversal leaves the validated resource and context untouched."""
    resource = Patient.model_validate({"active": True})
    snapshot = resource.model_dump()
    assert evaluate(resource, "active") == [True]
    assert resource.model_dump() == snapshot
    with pytest.raises(FHIRPathError, match="singleton"):
        evaluate(None, "(1 | 2).is(Integer)")


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("name.first().subsetOf($this.name)", [True]),
        ("name.first().supersetOf($this.name)", [False]),
        ("name.first().given.combine(name.last().given)", ["Ada", "Grace"]),
        ("name.select(given.first().combine(given.last()))", ["Ada", "Ada", "Grace", "Grace"]),
        ("name.where(given.first().subsetOf(given)).given", ["Ada", "Grace"]),
    ],
)
def test_function_arguments_use_lexical_context(expression: str, expected: Collection) -> None:
    """Navigation changes a function's receiver without replacing its argument context."""
    patient = Patient.model_validate({"name": [{"given": ["Ada"]}, {"given": ["Grace"]}]})
    assert evaluate(patient, expression) == expected


def test_fluent_arguments_share_textual_context() -> None:
    """String-free calls obey the same argument scope as parsed syntax."""
    patient = Patient.model_validate({"name": [{"given": ["Ada"]}, {"given": ["Grace"]}]})
    expression = path("name").first().call("subsetOf", path("name"))
    assert evaluate(patient, expression) == [True]
