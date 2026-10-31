"""Typed historical regression cases for the pinned fhirpathpy baseline."""

from typing import Literal

import pydantic
import pytest
from fhirpathpy import compile_as_array, compile_as_first


class CustomModel:
    """Non-Pydantic input rejected by the historical helper boundary."""

    pass


class HumanName(pydantic.BaseModel):
    """Minimal HumanName shape for typed helper regression cases."""

    given: list[str]
    family: str


class ContactPoint(pydantic.BaseModel):
    """Minimal ContactPoint shape for typed helper regression cases."""

    system: Literal["phone", "email", "fax", "pager", "url", "sms", "other"]
    value: str
    use: Literal["home", "work", "temp", "old", "mobile"]


class Patient(pydantic.BaseModel):
    """Minimal Patient shape for typed helper regression cases."""

    resourceType: Literal["Patient"] = "Patient"  # noqa: N815
    name: list[HumanName]
    telecom: list[ContactPoint]


class Observation(pydantic.BaseModel):
    """Minimal Observation shape for typed helper regression cases."""

    resourceType: Literal["Observation"] = "Observation"  # noqa: N815


class BundleEntry(pydantic.BaseModel):
    """Minimal BundleEntry shape for typed helper regression cases."""

    resource: Patient | Observation


class Bundle(pydantic.BaseModel):
    """Minimal Bundle shape for typed helper regression cases."""

    resourceType: Literal["Bundle"] = "Bundle"  # noqa: N815
    type: Literal["searchset"]
    entry: list[BundleEntry]


CUSTOM_MODEL = CustomModel()
PATIENT_DATA = {
    "resourceType": "Patient",
    "name": [
        {"given": ["First", "Middle"], "family": "Last"},
    ],
    "telecom": [
        {"system": "phone", "value": "555-555-2003", "use": "work"},
        {"system": "phone", "value": "555-555-2001", "use": "home"},
    ],
}
PATIENT_RESOURCE = Patient.model_validate(PATIENT_DATA)
BUNDLE_RESOURCE = Bundle(type="searchset", entry=[BundleEntry(resource=PATIENT_RESOURCE)])

EXPRESSION = "Patient.name.given"


@pytest.mark.parametrize(
    ("resource", "path", "input_type", "output_type", "expected"),
    [
        (PATIENT_DATA, EXPRESSION, dict, str, "First"),
        (PATIENT_RESOURCE, EXPRESSION, Patient, str, "First"),
        (PATIENT_DATA, "Patient.gender", dict, str, None),
        (
            BUNDLE_RESOURCE,
            "Bundle.entry.resource.where(resourceType='Patient')",
            Bundle,
            Patient,
            PATIENT_RESOURCE,
        ),
    ],
)
def compile_as_first_test[I, O](
    resource: I, path: str, input_type: type[I], output_type: type[O], expected: O | None
) -> None:
    """The typed helper returns the first result or None."""
    wrapper_fn = compile_as_first(path, input_type, output_type)
    result = wrapper_fn(resource)
    assert isinstance(result, output_type) or result is None
    assert result == expected


@pytest.mark.parametrize(
    ("resource", "path", "input_type", "output_type", "expected"),
    [
        (PATIENT_DATA, EXPRESSION, dict, str, ["First", "Middle"]),
        (PATIENT_RESOURCE, EXPRESSION, Patient, str, ["First", "Middle"]),
        (
            BUNDLE_RESOURCE,
            "Bundle.entry.resource.where(resourceType='Patient')",
            Bundle,
            Patient,
            [PATIENT_RESOURCE],
        ),
    ],
)
def compile_as_array_test[I, O](
    resource: I, path: str, input_type: type[I], output_type: type[O], expected: list[O]
) -> None:
    """The typed helper returns every result with the declared output type."""
    wrapper_fn = compile_as_array(path, input_type, output_type)
    result = wrapper_fn(resource)
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, output_type)
    assert result == expected


@pytest.mark.parametrize(
    ("resource", "path", "input_type", "output_type", "expected"),
    [
        (
            PATIENT_RESOURCE,
            EXPRESSION,
            Observation,
            str,
            "Resource type is Patient, expected Observation",
        ),
        (
            CUSTOM_MODEL,
            "Patient.name",
            type(CUSTOM_MODEL),
            str,
            "Don't know how to work with type CustomModel",
        ),
        (
            PATIENT_DATA,
            "Patient.telecom.value",
            dict,
            int,
            "Expected result to be int, but got str",
        ),
    ],
)
def exception_compile_as_first_test[I, O](
    resource: I, path: str, input_type: type[I], output_type: type[O], expected: str
) -> None:
    """The first-result helper rejects invalid input and output types."""
    wrapper_fn = compile_as_first(path, input_type, output_type)
    with pytest.raises(Exception) as exc:
        wrapper_fn(resource)
    assert str(exc.value) == expected


@pytest.mark.parametrize(
    ("resource", "path", "input_type", "output_type", "expected"),
    [
        (
            PATIENT_RESOURCE,
            EXPRESSION,
            Observation,
            str,
            "Resource type is Patient, expected Observation",
        ),
    ],
)
def exception_compile_as_array_test[I, O](
    resource: I, path: str, input_type: type[I], output_type: type[O], expected: str
) -> None:
    """The array helper rejects a mismatched resource type."""
    wrapper_fn = compile_as_array(path, input_type, output_type)
    with pytest.raises(Exception) as exc:
        wrapper_fn(resource)
    assert str(exc.value) == expected
