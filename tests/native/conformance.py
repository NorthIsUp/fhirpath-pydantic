"""Measure every upstream scenario against validated native FHIR resources."""

import json
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

import yaml
from fhir.resources import get_fhir_model_class as r5_model
from fhir.resources.R4B import get_fhir_model_class as r4b_model
from pydantic import BaseModel, Field, RootModel, TypeAdapter, ValidationError

from fhirpath_pydantic import FHIRPathError, QuantityValue, UnsupportedFeatureError, evaluate
from fhirpath_pydantic.operators import equal
from fhirpath_pydantic.types import Collection, Value

_MAPPING = TypeAdapter[dict[str, Value]](dict[str, Value])
type Status = Literal[
    "passed", "failed", "unsupported", "input_rejected", "unexpected_error", "disabled", "missing_expected"
]


class FixtureInput(BaseModel):
    """One validated input and its source FHIR release."""

    value: Value = None

    @classmethod
    def from_value(cls, value: Value, release: str | None = None) -> Self:
        """Use native models for real resources; generic language subjects may be maps."""
        if isinstance(value, dict) and isinstance(name := value.get("resourceType"), str):
            factory = r5_model if release == "r5" else r4b_model
            try:
                model = factory(name)
            except ValueError:
                return cls(value=value)
            return cls(value=model.model_validate(value))
        return cls(value=value)

    @classmethod
    @lru_cache(maxsize=64)
    def from_file(cls, path: Path, release: str | None = None) -> FixtureInput:
        """Validate each resource fixture without invoking the legacy loader."""
        return cls.from_value(_MAPPING.validate_json(path.read_text()), release)


class ExpectedValue(RootModel[Value]):
    """Compare analogous native values rather than requiring JSON compatibility."""

    def matches(self, actual: Value) -> bool:
        """Adapt a declared expectation to the result's native model or scalar type."""
        expected = self.root
        if isinstance(actual, QuantityValue) and isinstance(expected, str):
            quantity = QuantityValue.from_text(expected)
            return quantity is not None and actual.equals(quantity) is True
        if isinstance(actual, BaseModel) and isinstance(expected, dict):
            try:
                return equal(actual, type(actual).model_validate(expected)) is True
            except ValidationError:
                return False
        if isinstance(expected, str):
            try:
                match actual:
                    case datetime():
                        return actual == datetime.fromisoformat(expected)
                    case date():
                        return actual == date.fromisoformat(expected)
                    case time():
                        return actual == time.fromisoformat(expected.removeprefix("T"))
                    case _:
                        pass
            except ValueError:
                return False
        return equal(actual, expected) is True


class BoundExpression(BaseModel):
    """Legacy fragment metadata is preserved until its native-input adaptation is verified."""

    base: str
    expression: str


class FixtureCase(BaseModel):
    """A typed leaf from the upstream suite before expression-list expansion."""

    expression: str | list[str] | BoundExpression
    expected: Collection | None = Field(default=None, alias="result")
    error: bool = False
    disable: bool = False
    description: str = Field(default="", alias="desc")
    input_file: str | None = Field(default=None, alias="inputfile")
    release: str | None = Field(default=None, alias="model")
    context: str | None = None
    variables: dict[str, Value] = Field(default_factory=dict[str, Value])

    def expects_error(self) -> bool:
        """Recognize both upstream error markers without treating errors as data."""
        return self.error or (
            self.expected is not None
            and len(self.expected) == 1
            and isinstance(self.expected[0], dict)
            and self.expected[0].get("$status") == "error"
        )

    def expressions(self) -> tuple[str | BoundExpression, ...]:
        """Expression lists define independent assertions, not one mutable case."""
        return tuple(self.expression) if isinstance(self.expression, list) else (self.expression,)

    def run(self, expression: str | BoundExpression, subject: Value, resources: Path) -> tuple[Status, str]:
        """Execute error assertions; unsupported features never count as successful errors."""
        if self.disable:
            return "disabled", "Disabled in upstream"
        if isinstance(expression, BoundExpression):
            return "unsupported", f"Native fragment adaptation required for {expression.base}"
        try:
            source = (
                FixtureInput.from_file(resources / self.input_file, self.release)
                if self.input_file is not None
                else FixtureInput.from_value(subject, self.release)
            )
        except ValidationError as error:
            return "input_rejected", f"FHIR validation rejected {error.error_count()} field(s)"
        variables: dict[str, Value] = {"resource": source.value, **self.variables}
        try:
            if self.context is not None:
                selected = evaluate(source.value, self.context, variables)
                variables["context"] = selected[0] if selected else None
            actual = evaluate(source.value, expression, variables)
        except UnsupportedFeatureError as error:
            return "unsupported", str(error)
        except (FHIRPathError, ValidationError) as error:
            return ("passed", "Expected domain error") if self.expects_error() else ("failed", type(error).__name__)
        except Exception as error:
            # Interpreter defects must remain distinct from expected domain errors.
            return "unexpected_error", type(error).__name__
        if self.expects_error():
            return "failed", "Expected an error, but evaluation succeeded"
        if self.expected is None:
            return "missing_expected", "No expected result declared"
        if len(actual) != len(self.expected):
            return "failed", f"Result cardinality {len(actual)} differs from expected {len(self.expected)}"
        if all(
            ExpectedValue.model_construct(root=expected).matches(value)
            for value, expected in zip(actual, self.expected, strict=True)
        ):
            return "passed", "Native result matches expectation"
        return "failed", "Native result differs from expectation"


class FixtureNode(RootModel[dict[str, Value]]):
    """Dynamic upstream group-title keys have a validated mapping boundary."""

    def cases(self, subject: Value, disabled: bool = False) -> Iterator[tuple[FixtureCase, Value]]:
        """Flatten every group, preserving inherited subject and disable flags."""
        disabled = disabled or self.root.get("disable") is True
        subject = self.root.get("subject", subject)
        groups = [value for name, value in self.root.items() if name.startswith("group")]
        if groups:
            for group in groups:
                if not isinstance(group, list):
                    raise ValueError("A fixture group must contain a list")
                for child in group:
                    yield from type(self).model_validate(child).cases(subject, disabled)
        elif "expression" in self.root:
            case = FixtureCase.model_validate(self.root)
            yield case.model_copy(update={"disable": disabled or case.disable}), subject


class FixtureSuite(BaseModel):
    """One upstream YAML file validated before any fixture fields are read."""

    tests: list[FixtureNode]
    subject: Value = None

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Validate PyYAML's external result at its input boundary."""
        # JSON normalization makes YAML numeric mapping keys match the FHIRPath
        # object model, whose member names are strings.
        return cls.model_validate_json(json.dumps(yaml.safe_load(path.read_text())))

    def cases(self) -> Iterator[tuple[FixtureCase, Value]]:
        """Include every declared scenario, including explicit upstream exclusions."""
        for node in self.tests:
            yield from node.cases(self.subject)


class CaseOutcome(BaseModel):
    """Execution metadata contains no resource payloads or returned clinical values."""

    source: str
    ordinal: int
    expression: str | BoundExpression
    status: Status
    reason: str


class ConformanceReport(BaseModel):
    """Measured upstream coverage, including all unsupported or invalid-input cases."""

    outcomes: list[CaseOutcome] = Field(default_factory=list[CaseOutcome])

    @classmethod
    def from_directory(cls, directory: Path, resources: Path) -> Self:
        """Execute all YAML files without filtering out any feature categories."""
        report = cls()
        for path in sorted(directory.glob("*.yaml")):
            suite = FixtureSuite.from_file(path)
            ordinal = 0
            for case, subject in suite.cases():
                for expression in case.expressions():
                    ordinal += 1
                    status, reason = case.run(expression, subject, resources)
                    report.outcomes.append(
                        CaseOutcome(
                            source=path.name, ordinal=ordinal, expression=expression, status=status, reason=reason
                        )
                    )
        return report

    def counts(self) -> dict[str, int]:
        """Rejected fixtures and missing expectations are never counted as passes."""
        return dict(Counter(outcome.status for outcome in self.outcomes))

    def complete(self) -> bool:
        """Every enabled assertion must pass before this report claims parity."""
        return any(outcome.status == "passed" for outcome in self.outcomes) and all(
            outcome.status in {"passed", "disabled"} for outcome in self.outcomes
        )

    @classmethod
    def main(cls) -> int:
        """Persist the full audit and fail the command while any gap remains."""
        root = Path(__file__).resolve().parents[2]
        report = cls.from_directory(root / "tests" / "cases", root / "tests" / "resources")
        path = root / "dist" / "parity-report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2) + "\n")
        print(report.counts())
        print(f"Full report: {path}")
        return 0 if report.complete() else 1


if __name__ == "__main__":
    raise SystemExit(ConformanceReport.main())
