"""Bound the official audit's unsupported cases against the actual pinned baseline."""

from collections import Counter
from importlib.resources import files
from pathlib import Path
from xml.etree import ElementTree

from hl7_conformance import HL7Report
from test_registry import BaselineRegistry

_APPROVED_UNSUPPORTED: dict[str, int] = {
    "Unsupported FHIRPath function: lowBoundary": 114,
    "Unsupported FHIRPath function: highBoundary": 99,
    "Unsupported FHIRPath function: sort": 30,
    "Unsupported FHIRPath function: defineVariable": 20,
    "Unsupported FHIRPath function: matchesFull": 15,
    "Unsupported FHIRPath function: unescape": 12,
    "Unsupported FHIRPath function: escape": 9,
    "Unsupported FHIRPath function: conformsTo": 9,
    "Unsupported FHIRPath function: comparable": 9,
    "Evaluation mode not implemented: custom": 213,
    "Evaluation mode not implemented: semantic": 114,
    "Evaluation mode not implemented: strict": 18,
    "Evaluation mode not implemented: html": 4,
    "Evaluation mode not implemented: cda": 3,
    "Evaluation mode not implemented: tx": 3,
    "Evaluation mode not implemented: lenient/polymorphics": 2,
}


def test_every_unsupported_official_case_has_reviewed_scope() -> None:
    """No missing baseline function can hide inside an unsupported official category."""
    root = Path(__file__).parents[2]
    report = HL7Report.from_corpus(root)
    registry = BaselineRegistry.from_source(files("fhirpathpy.engine.invocations").joinpath("__init__.py").read_text())
    reasons = Counter(outcome.reason for outcome in report.outcomes if outcome.status == "unsupported")
    assert reasons == Counter(_APPROVED_UNSUPPORTED)
    for reason in reasons:
        if reason.startswith("Unsupported FHIRPath function: "):
            name = reason.removeprefix("Unsupported FHIRPath function: ")
            assert name not in registry.functions(), name
        else:
            assert reason.startswith("Evaluation mode not implemented: "), reason


def test_document_modes_are_explicit_optional_reference_extensions() -> None:
    """Each pinned suite declares these functions outside both FHIRPath and FHIR's additions."""
    root = Path(__file__).parents[1] / "hl7"
    registry = BaselineRegistry.from_source(files("fhirpathpy.engine.invocations").joinpath("__init__.py").read_text())
    for release in ("r4", "r4b", "r5"):
        groups = [
            node
            for node in ElementTree.parse(root / release / "tests.xml").iter()
            if node.get("name") == "documentFunctions"
        ]
        [group] = groups
        assert group.get("mode") == "custom"
        assert "not part of FHIRPath" in (group.get("description") or "")
        assert "extension of the HL7 Java reference implementation" in (group.get("description") or "")
    assert not registry.functions().intersection(
        {"section", "entry", "entryIn", "resources", "resourcesIn", "sameSubject", "hasCoding"}
    )
