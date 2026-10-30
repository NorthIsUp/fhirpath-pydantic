"""Execute reviewed native expectations without hiding raw conformance failures."""

from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from xml.etree import ElementTree

import pytest
from conformance import BoundExpression, FixtureCase, FixtureSuite
from hl7_conformance import HL7Case, HL7Output
from pydantic import BaseModel, ConfigDict, Field

from fhirpath_pydantic import query
from fhirpath_pydantic.engine import State
from fhirpath_pydantic.types import Collection, Value


class ReviewClock(State):
    """Give timestamp-format assertions a deterministic, nonzero microsecond value."""

    timestamp: datetime = datetime(2024, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)


class NativeExpectation(BaseModel):
    """An independently chosen native result and its compatibility rationale."""

    model_config = ConfigDict(frozen=True)
    expected: Collection = Field(default_factory=list[Value])
    error: bool = False
    occurrences: int = 1
    rationale: str = Field(min_length=1)

    def check_yaml(self, case: FixtureCase, expression: str | BoundExpression, subject: Value, resources: Path) -> None:
        """Run the original input and expression with only the reviewed expectation changed."""
        native = case.model_copy(update={"expected": self.expected, "error": self.error})
        assert native.run(expression, subject, resources)[0] == "passed", (expression, self.rationale)

    def check_hl7(self, case: HL7Case, directory: Path, release: str) -> None:
        """Preserve official input, context and modes when checking the native contract."""
        outputs: list[HL7Output] = []
        for value in self.expected:
            match value:
                case datetime():
                    output = HL7Output(type="dateTime", text=value.isoformat())
                case date():
                    output = HL7Output(type="date", text=value.isoformat())
                case bool():
                    output = HL7Output(type="boolean", text="true" if value else "false")
                case int():
                    output = HL7Output(type="integer", text=str(value))
                case str():
                    output = HL7Output(type="string", text=value)
                case _:
                    raise ValueError("The review must explicitly support each expected output type")
            outputs.append(output)
        native = case.model_copy(update={"outputs": outputs, "invalid": "execution" if self.error else None})
        assert native.run(directory, release)[0] == "passed", (case.expression, self.rationale)


YAML_REVIEWS: dict[str, NativeExpectation] = {
    "'1 year'.toQuantity() != 1 'a'": NativeExpectation(
        rationale="Calendar years and mean UCUM years cannot be definitely equal or unequal without conversion."
    ),
    "now().toString().substring(11,12) = timeOfDay().toString()": NativeExpectation(
        expected=[False], rationale="Native timestamps retain six microsecond digits, so twelve characters truncate."
    ),
    "timeOfDay().toString().length() = 12": NativeExpectation(
        expected=[False], rationale="Full native microsecond precision is not restricted to milliseconds."
    ),
    "1 > 2 is Boolean": NativeExpectation(
        error=True, occurrences=2, rationale="Normative precedence parses 1 > (2 is Boolean), an invalid ordering."
    ),
    "Patient.id is System.String": NativeExpectation(
        expected=[False], rationale="Declared FHIR.id identity is retained; getValue() exposes System.String."
    ),
    "Patient.birthDate + 1 day = @1974-12-26": NativeExpectation(
        expected=[True], rationale="A validated native birthDate supports calendar arithmetic."
    ),
    "Functions.attrtrue.extension('url1').extension('url2').value = 'someuri'": NativeExpectation(
        rationale="Synthetic dictionary Functions has no native choice metadata; the R4B/R5 analogue is tested separately."
    ),
    "Patient.birthDate != @1974-12-25T12:34:00-10:00": NativeExpectation(
        rationale="The date has no time precision; inequality at time precision is indeterminate."
    ),
    "Patient.birthDate != @1974-12-25T12:34:00+10:00": NativeExpectation(
        rationale="The date has no time precision; inequality at time precision is indeterminate."
    ),
    "Patient.birthDate != @1974-12-25T12:34:00Z": NativeExpectation(
        rationale="The date has no time precision; inequality at time precision is indeterminate."
    ),
    "1 | 1 is Integer": NativeExpectation(
        expected=[1, True], rationale="Type tests bind before union; Integer 1 and Boolean true remain distinct."
    ),
    "Patient.is(System.Patient).not()": NativeExpectation(
        error=True, rationale="System.Patient does not exist; unresolved type names raise a domain error."
    ),
}

HL7_REVIEWS: dict[str, NativeExpectation] = {
    "@T14:34:28Z.is(Time)": NativeExpectation(
        expected=[True], occurrences=3, rationale="Native Time offsets are an explicit supported extension."
    ),
    "@T14:34:28+10:00.is(Time)": NativeExpectation(
        expected=[True], occurrences=3, rationale="Native Time offsets are an explicit supported extension."
    ),
    "1 year < 2 months": NativeExpectation(
        expected=[False], occurrences=3, rationale="Current FHIRPath defines unanchored calendar conversion factors."
    ),
    "1 year <= 2 days": NativeExpectation(
        expected=[False], occurrences=3, rationale="Current FHIRPath defines unanchored calendar conversion factors."
    ),
    "1 year > 2 months": NativeExpectation(
        expected=[True], occurrences=3, rationale="Current FHIRPath defines unanchored calendar conversion factors."
    ),
    "@1973-12-25T00:00:00.000+10:00 + 0.1 's'": NativeExpectation(
        expected=[datetime.fromisoformat("1973-12-25T00:00:00.100+10:00")],
        occurrences=2,
        rationale="Fractional seconds survive arithmetic; the R5 version already expects this result.",
    ),
    "Patient.is(System.Patient).not()": NativeExpectation(
        error=True,
        occurrences=3,
        rationale="Unresolved System.Patient errors are explicitly permitted by the test description.",
    ),
    "Observation.valueQuantity.exists()": NativeExpectation(
        expected=[True],
        occurrences=3,
        rationale="Native Pydantic field aliases remain accessible alongside choice groups.",
    ),
    "Patient.gender.as(string)": NativeExpectation(
        expected=["male"],
        occurrences=3,
        rationale="FHIR.code specializes FHIR.string; upcasting keeps the original value and declared code identity.",
    ),
    "Patient.gender.ofType(string)": NativeExpectation(
        expected=["male"],
        occurrences=3,
        rationale="ofType includes subclasses, so a declared FHIR.code is included when selecting FHIR.string.",
    ),
    "'a'.combine('b').combine('a').distinct()": NativeExpectation(
        expected=["a", "b"], rationale="Distinct keeps first occurrences; FHIRPath does not guarantee the output order."
    ),
    "1.combine(2).combine(1).combine(3).distinct()": NativeExpectation(
        expected=[1, 2, 3], rationale="Distinct keeps first occurrences; FHIRPath does not guarantee the output order."
    ),
    "1.combine(2).combine(1.0).distinct()": NativeExpectation(
        expected=[1, 2], rationale="Numerically equal Integer/Decimal values deduplicate at the first occurrence."
    ),
    "true.combine(false).combine(true).distinct()": NativeExpectation(
        expected=[True, False],
        rationale="Distinct keeps first occurrences; FHIRPath does not guarantee the output order.",
    ),
    "@2020-01-01.combine(@2020-01-02).combine(@2020-01-01).distinct()": NativeExpectation(
        expected=[date(2020, 1, 1), date(2020, 1, 2)],
        rationale="Native dates deduplicate at the first occurrence without changing their representation.",
    ),
}


def test_every_baseline_difference_has_a_native_expectation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every failing original assertion needs an explicit executable native decision."""
    monkeypatch.setattr(query, "State", ReviewClock)
    root = Path(__file__).parents[2]
    failures: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    for path in sorted((root / "tests/cases").glob("*.yaml")):
        for case, subject in FixtureSuite.from_file(path).cases():
            for expression in case.expressions():
                status = case.run(expression, subject, root / "tests/resources")[0]
                statuses[status] += 1
                if status == "failed":
                    assert isinstance(expression, str)
                    assert expression in YAML_REVIEWS, (path.name, expression)
                    YAML_REVIEWS[expression].check_yaml(case, expression, subject, root / "tests/resources")
                    failures[expression] += 1
    assert failures == Counter({expression: review.occurrences for expression, review in YAML_REVIEWS.items()})
    assert statuses == Counter(passed=1387, failed=13, input_rejected=75, disabled=70)


def test_every_hl7_difference_has_a_native_expectation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Official failures require individual decisions across all three release suites."""
    monkeypatch.setattr(query, "State", ReviewClock)
    root = Path(__file__).parents[1] / "hl7"
    failures: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    for release in ("r4", "r4b", "r5"):
        directory = root / release
        for case in HL7Case.from_group(ElementTree.parse(directory / "tests.xml").getroot()):
            status = case.run(directory, release)[0]
            statuses[status] += 1
            if status == "failed":
                assert case.expression in HL7_REVIEWS, (release, case.name, case.expression)
                HL7_REVIEWS[case.expression].check_hl7(case, directory, release)
                failures[case.expression] += 1
    assert failures == Counter({expression: review.occurrences for expression, review in HL7_REVIEWS.items()})
    assert statuses == Counter(passed=2854, failed=34, unsupported=690, input_rejected=35)
