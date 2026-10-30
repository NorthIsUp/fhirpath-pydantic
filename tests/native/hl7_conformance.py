"""Audit every case in the pinned official HL7 R4, R4B and R5 corpora."""

from decimal import Decimal, InvalidOperation
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self
from xml.etree import ElementTree

from conformance import CaseOutcome, ConformanceReport, ExpectedValue, FixtureInput, Status
from fhir.resources import get_fhir_model_class as r5_model
from fhir.resources.R4B import get_fhir_model_class as r4b_model
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from fhirpath_pydantic import FHIRPathError, QuantityValue, TemporalValue, UnsupportedFeatureError, compile, evaluate
from fhirpath_pydantic.native import Item, items
from fhirpath_pydantic.types import Collection, Value

_BOOL = TypeAdapter[bool](bool)


class SourceDigest(BaseModel):
    """An official artifact's byte digest prevents silent corpus changes."""

    local_path: str
    repository_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def verify(self, root: Path) -> None:
        """Require each pinned input artifact to match its recorded content."""
        if sha256((root / self.local_path).read_bytes()).hexdigest() != self.sha256:
            raise ValueError(f"Official corpus artifact changed: {self.local_path}")


class SourceManifest(BaseModel):
    """All three releases and their input files come from one immutable revision."""

    revision: Literal["db9fce391702b896c4e340dcb035ef44feb57093"]
    releases: tuple[Literal["r4", "r4b", "r5"], ...]
    files: list[SourceDigest]

    def verify(self, root: Path) -> None:
        """Verify licensing, suites and inputs before attempting any assertions."""
        if set(self.releases) != {"r4", "r4b", "r5"}:
            raise ValueError("The official audit requires all three release suites")
        for source in self.files:
            source.verify(root)


class HL7Input(FixtureInput):
    """Official XML and JSON resources are parsed by the owning FHIR models."""

    @classmethod
    @lru_cache(maxsize=64)
    def from_path(cls, path: Path, release: str) -> HL7Input:
        """Use vendor model_validate_xml rather than a hand-built XML-to-FHIR mapping."""
        if path.suffix == ".json":
            return cls(value=FixtureInput.from_file(path, release).value)
        tree = ElementTree.parse(path).getroot()
        if not tree.tag.startswith("{http://hl7.org/fhir}"):
            raise ValueError("Input is not a FHIR resource")
        model = (r5_model if release == "r5" else r4b_model)(tree.tag.rsplit("}", 1)[-1])
        return cls(value=model.model_validate_xml(path.read_bytes()))


class HL7Output(BaseModel):
    """Literal expectations are parsed independently of the interpreter being tested."""

    type: str | None = None
    text: str

    def value(self) -> Value:
        """Keep typed primitive expectations native and preserve Decimal precision."""
        kind, text = self.type, self.text
        if kind in {"string", "code", "id", "uri", "url", "canonical"}:
            return text
        if kind == "boolean" or kind is None and text in {"true", "false"}:
            return _BOOL.validate_json(text)
        if kind in {"integer", "long", "integer64"}:
            return int(text)
        if kind in {"date", "dateTime", "time"} or text.startswith("@"):
            temporal_kind = (
                "Time"
                if kind == "time" or text.startswith("@T")
                else "DateTime"
                if kind == "dateTime" or "T" in text
                else "Date"
            )
            return TemporalValue.from_text(text, temporal_kind).native()
        if kind == "Quantity" or kind is None and "'" in text:
            if (quantity := QuantityValue.from_text(text)) is None:
                raise ValueError("Invalid expected Quantity literal")
            return quantity
        if kind == "decimal" or kind is None:
            try:
                return Decimal(text)
            except InvalidOperation as error:
                raise ValueError("Invalid untyped expected literal") from error
        raise UnsupportedFeatureError(f"Unsupported expected HL7 output type: {kind}")


class HL7Case(BaseModel):
    """Every XML test carries its original assertion and evaluation configuration."""

    name: str
    input_file: str | None = Field(default=None, alias="inputfile")
    context: str | None = None
    context_type: str | None = Field(default=None, alias="contextType")
    predicate: bool = False
    ordered: bool = True
    mode: str | None = None
    expression: str = ""
    invalid: str | None = None
    outputs: list[HL7Output] = Field(default_factory=list[HL7Output])

    @classmethod
    def from_element(cls, node: ElementTree.Element, mode: str | None = None) -> Self:
        """Read both unnamespaced R4 and namespaced R5 XML without dropping cases."""
        case = cls.model_validate(node.attrib)
        expressions = [child for child in node if child.tag.rsplit("}", 1)[-1] == "expression"]
        if len(expressions) != 1:
            raise ValueError("Each HL7 case must declare exactly one expression")
        expression = expressions[0]
        return case.model_copy(
            update={
                "expression": expression.text or "",
                "invalid": expression.get("invalid"),
                "mode": case.mode or expression.get("mode") or mode,
                "outputs": [
                    HL7Output(type=child.get("type"), text=child.text or "")
                    for child in node
                    if child.tag.rsplit("}", 1)[-1] == "output"
                ],
            }
        )

    @classmethod
    def from_group(cls, node: ElementTree.Element, mode: str | None = None) -> list[HL7Case]:
        """Include every group and mode, including optional and custom assertions."""
        mode = node.get("mode", mode)
        result: list[HL7Case] = []
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "test":
                result.append(cls.from_element(child, mode))
            elif tag == "group":
                result.extend(cls.from_group(child, mode))
        return result

    def run(self, directory: Path, release: str) -> tuple[Status, str]:
        """Execute supported modes and preserve unsupported configuration as findings."""
        if self.mode not in {None, "element"}:
            return "unsupported", f"Evaluation mode not implemented: {self.mode}"
        if self.context_type is not None:
            return "unsupported", "Static context type declaration is not implemented"
        try:
            source = (
                HL7Input.from_path(directory / self.input_file, release).value if self.input_file is not None else None
            )
        except (ValidationError, ValueError) as error:
            return "input_rejected", type(error).__name__
        except Exception as error:
            return "unexpected_error", f"Input adapter: {type(error).__name__}"
        try:
            query = compile(self.expression)
        except FHIRPathError:
            return (
                ("passed", "Expected syntax error")
                if self.invalid == "syntax"
                else ("failed", "Unexpected syntax error")
            )
        if self.invalid == "syntax":
            return "failed", "Expected syntax error, but compilation succeeded"
        variables: dict[str, Value] = {"resource": source, "rootResource": source}
        try:
            focus = source
            if self.context is not None:
                selected = evaluate(source, self.context)
                focus = selected[0] if len(selected) == 1 else selected
            variables["context"] = focus
            actual = query(focus, variables)
            if self.predicate:
                actual = [Item.boolean(items(actual))]
        except UnsupportedFeatureError as error:
            return "unsupported", str(error)
        except FHIRPathError, ValidationError:
            return (
                ("passed", "Expected evaluation error")
                if self.invalid is not None
                else ("failed", "Unexpected evaluation error")
            )
        except Exception as error:
            return "unexpected_error", type(error).__name__
        if self.invalid is not None:
            return "failed", "Expected evaluation error, but evaluation succeeded"
        try:
            expected: Collection = [output.value() for output in self.outputs]
        except UnsupportedFeatureError as error:
            return "unsupported", str(error)
        except ValueError:
            return "failed", "Invalid expected output literal"
        if len(actual) != len(expected):
            return "failed", f"Result cardinality {len(actual)} differs from expected {len(expected)}"
        if self.ordered:
            matched = all(
                ExpectedValue.model_construct(root=value).matches(item)
                for item, value in zip(actual, expected, strict=True)
            )
        else:
            remaining = list(actual)
            for value in expected:
                for index, item in enumerate(remaining):
                    if ExpectedValue.model_construct(root=value).matches(item):
                        remaining.pop(index)
                        break
                else:
                    return "failed", "Unordered result differs from expectation"
            matched = not remaining
        return (
            ("passed", "Native result matches expectation")
            if matched
            else ("failed", "Native result differs from expectation")
        )


class HL7Report(ConformanceReport):
    """A complete audit retains every official assertion in all three releases."""

    @classmethod
    def from_corpus(cls, root: Path) -> Self:
        """Verify provenance and execute the full corpus without selecting feature categories."""
        manifest = SourceManifest.model_validate_json((root / "tests/hl7/sources.json").read_bytes())
        manifest.verify(root)
        report = cls()
        for release in manifest.releases:
            directory = root / "tests/hl7" / release
            cases = HL7Case.from_group(ElementTree.parse(directory / "tests.xml").getroot())
            if not cases:
                raise ValueError(f"No cases collected for {release}")
            recorded = {source.local_path for source in manifest.files}
            referenced = {
                (directory / case.input_file).relative_to(root).as_posix()
                for case in cases
                if case.input_file is not None
            }
            if not referenced <= recorded:
                raise ValueError(f"Official corpus inputs lack provenance: {sorted(referenced - recorded)}")
            for ordinal, case in enumerate(cases, start=1):
                status, reason = case.run(directory, release)
                report.outcomes.append(
                    CaseOutcome(
                        source=f"hl7/{release}/{case.name}",
                        ordinal=ordinal,
                        expression=case.expression,
                        status=status,
                        reason=reason,
                    )
                )
        return report

    @classmethod
    def audit(cls) -> int:
        """Write every outcome and return nonzero while conformance gaps remain."""
        root = Path(__file__).resolve().parents[2]
        report = cls.from_corpus(root)
        destination = root / "dist/hl7-report.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(report.model_dump_json(indent=2) + "\n")
        print(report.counts())
        print(f"Full report: {destination}")
        return 0 if report.complete() else 1


if __name__ == "__main__":
    raise SystemExit(HL7Report.audit())
