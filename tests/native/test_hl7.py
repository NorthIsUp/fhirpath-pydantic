"""The official audit preserves every case, validates inputs, and executes errors."""

from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fhir.resources.patient import Patient
from hl7_conformance import HL7Case, HL7Input, HL7Output, SourceDigest, SourceManifest

from fhirpath_pydantic import evaluate


@pytest.mark.parametrize("namespace", ["", ' xmlns="http://hl7.org/fhirpath/tests"'])
def test_namespaced_suites_collect_every_case(namespace: str) -> None:
    """R5 namespace changes cannot silently turn a full corpus into zero cases."""
    source = ElementTree.fromstring(
        f'<tests{namespace}><group mode="custom"><test name="custom"><expression>1</expression></test></group><test name="plain"><expression>2</expression></test></tests>'
    )
    cases = HL7Case.from_group(source)
    assert [(case.name, case.mode) for case in cases] == [("custom", "custom"), ("plain", None)]


@pytest.mark.parametrize(
    ("expression", "invalid", "status"),
    [
        ("1 +", "syntax", "passed"),
        ("(1 | 2).single()", "execution", "passed"),
        ("1", "execution", "failed"),
        ("1.unimplemented()", "execution", "unsupported"),
        ("1.unimplemented()", "syntax", "failed"),
    ],
)
def test_hl7_expected_errors_are_real(expression: str, invalid: str, status: str, tmp_path: Path) -> None:
    """Expected error phases are distinct; missing implementations never count as passes."""
    case = HL7Case(name="synthetic", expression=expression, invalid=invalid)
    assert case.run(tmp_path, "r5")[0] == status


def test_hl7_output_parser_preserves_decimal_precision() -> None:
    """Expected literal parsing must not reuse the tested evaluation engine."""
    text = "123456789012345678901234567890.0012"
    assert HL7Output(type="decimal", text=text).value() == Decimal(text)
    assert HL7Output(text=text).value() == Decimal(text)


def test_hl7_predicate_uses_singleton_boolean_rules(tmp_path: Path) -> None:
    """A native Date predicate is present even though it is not a Boolean scalar."""
    case = HL7Case(
        name="synthetic", expression="@2018-01-01", predicate=True, outputs=[HL7Output(type="boolean", text="true")]
    )
    assert case.run(tmp_path, "r5")[0] == "passed"


@pytest.mark.parametrize(("release", "count"), [("r4", 1153), ("r4b", 1151), ("r5", 1309)])
def test_official_case_counts_are_complete(release: str, count: int) -> None:
    """The pinned suite counts include custom modes and every feature category."""
    root = Path(__file__).parents[1] / "hl7"
    cases = HL7Case.from_group(ElementTree.parse(root / release / "tests.xml").getroot())
    assert len(cases) == count
    assert any(case.mode == "custom" for case in cases)


def test_official_artifact_digests_are_verified() -> None:
    """Committed corpus bytes remain tied to the declared official revision."""
    root = Path(__file__).parents[2]
    manifest = SourceManifest.model_validate_json((root / "tests/hl7/sources.json").read_bytes())
    manifest.verify(root)


def test_changed_artifact_digest_is_rejected(tmp_path: Path) -> None:
    """A locally modified upstream input cannot silently change the audit baseline."""
    source = SourceDigest(
        local_path="data.xml", repository_path="synthetic/data.xml", sha256=sha256(b"original").hexdigest()
    )
    (tmp_path / "data.xml").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        source.verify(tmp_path)


def test_official_xml_uses_native_fhir_model() -> None:
    """The XML input boundary uses fhir.resources rather than a dynamic FHIR dict."""
    path = Path(__file__).parents[1] / "hl7/r5/patient-example.xml"
    resource = HL7Input.from_path(path, "r5").value
    assert isinstance(resource, Patient)
    assert evaluate(resource, "name.given") == ["Peter", "James", "Jim", "Peter", "James"]


def test_fractional_datetime_expected_value(tmp_path: Path) -> None:
    """The audit compares the native DateTime without losing fractional seconds."""
    case = HL7Case(
        name="fractional-second",
        expression="@1973-12-25T00:00:00.000+10:00 + 0.1 's'",
        outputs=[HL7Output(type="dateTime", text="@1973-12-25T00:00:00.100+10:00")],
    )
    assert case.run(tmp_path, "r5") == ("passed", "Native result matches expectation")
