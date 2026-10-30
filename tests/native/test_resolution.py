"""Native reference resolution is explicit, scoped and identity-preserving."""

import pytest
from fhir.resources.bundle import Bundle
from fhir.resources.observation import Observation
from fhir.resources.patient import Patient
from pydantic import BaseModel, RootModel

from fhirpath_pydantic import EvaluationOptions, FHIRPathError, evaluate


class ReferenceMap(RootModel[dict[str, BaseModel]]):
    """A deterministic caller-owned resolver with no network access."""

    def resolve(self, reference: str) -> BaseModel | None:
        """Resolve one reference against the explicit test resource index."""
        return self.root.get(reference)


def test_caller_supplied_resolver_retains_identity() -> None:
    """An external reference resolves to the caller's original native resource."""
    patient = Patient.model_validate({"id": "target", "active": True})
    observation = Observation.model_validate(
        {"status": "final", "code": {"text": "resolve"}, "subject": {"reference": "Patient/target"}}
    )
    index = ReferenceMap.model_validate({"Patient/target": patient})
    options = EvaluationOptions(resolver=index.resolve)
    assert evaluate(observation, "subject.resolve()", options=options)[0] is patient
    assert evaluate(observation, "subject.resolve().active", options=options) == [True]
    assert evaluate(observation, "subject.resolve()") == []


def test_contained_reference_uses_its_resource_scope() -> None:
    """Two containing resources may safely reuse the same local contained id."""
    bundle = Bundle.model_validate(
        {
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Observation",
                        "status": "final",
                        "code": {"text": "first"},
                        "subject": {"reference": "#local"},
                        "contained": [{"resourceType": "Patient", "id": "local", "active": True}],
                    }
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "status": "final",
                        "code": {"text": "second"},
                        "subject": {"reference": "#local"},
                        "contained": [{"resourceType": "Patient", "id": "local", "active": False}],
                    }
                },
            ],
        }
    )
    assert evaluate(bundle, "entry.resource.subject.resolve().active") == [True, False]


def test_bundle_full_url_and_relative_reference() -> None:
    """A Bundle resolves fullUrl and relative type/id references locally."""
    bundle = Bundle.model_validate(
        {
            "type": "collection",
            "entry": [
                {"fullUrl": "urn:uuid:target", "resource": {"resourceType": "Patient", "id": "target", "active": True}}
            ],
        }
    )
    assert bundle.entry is not None
    patient = bundle.entry[0].resource
    assert evaluate(bundle, "'urn:uuid:target'.resolve()")[0] is patient
    assert evaluate(bundle, "'Patient/target'.resolve()")[0] is patient
    assert evaluate(bundle, "'Patient/missing'.resolve()") == []


def test_resolver_boundary_requires_a_pydantic_model() -> None:
    """A dynamically registered callable cannot inject a raw dictionary result."""

    def invalid(reference: str) -> dict[str, bool]:
        return {"active": bool(reference)}

    options = EvaluationOptions.model_validate({"resolver": invalid})
    with pytest.raises(FHIRPathError, match="Pydantic"):
        evaluate(None, "'Patient/target'.resolve()", options=options)
