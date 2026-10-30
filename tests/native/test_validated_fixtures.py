"""Rejected legacy payloads still have working, validated native equivalents."""

from pathlib import Path
from typing import Self

import pytest
from conformance import BoundExpression, FixtureCase, FixtureInput, FixtureSuite
from fhir.resources import get_fhir_model_class as r5_model
from fhir.resources.extension import Extension
from fhir.resources.fhirprimitiveextension import FHIRPrimitiveExtension
from fhir.resources.R4B import get_fhir_model_class as r4b_model
from fhir.resources.R4B.extension import Extension as R4BExtension
from fhir.resources.R4B.fhirprimitiveextension import FHIRPrimitiveExtension as R4BPrimitiveExtension
from pydantic import Field, TypeAdapter, ValidationError

from fhirpath_pydantic import FHIRPathError, evaluate
from fhirpath_pydantic.types import Value

_PAYLOAD = TypeAdapter[dict[str, Value]](dict[str, Value])


class CanonicalInput(FixtureInput):
    """Explicit test-fixture repairs leave production validation and upstream bytes intact."""

    @classmethod
    def from_payload(cls, payload: dict[str, Value], release: str) -> Self:
        """Validate a corrected fixture with the actual vendor resource model."""
        name = payload["resourceType"]
        assert isinstance(name, str)
        return cls(value=(r5_model if release == "r5" else r4b_model)(name).model_validate(payload))

    def check(self, case: FixtureCase, resources: Path) -> int:
        """Use original expressions and expectations with this validated native input."""
        native_case = case.model_copy(update={"input_file": None})
        for expression in case.expressions():
            assert native_case.run(expression, self.value, resources)[0] == "passed", expression
        return len(case.expressions())

    @classmethod
    def required_resource_fields(cls, payload: dict[str, Value]) -> dict[str, Value]:
        """Supply the exact missing fields in the nested choice-navigation fixture."""
        result = dict(payload)
        if result.get("resourceType") == "Observation":
            result.update(status="final", code={"text": "fixture"})
        elif result.get("resourceType") == "QuestionnaireResponse":
            result.update(status="completed", questionnaire="http://example.org/questionnaire")
        if isinstance(contained := result.get("contained"), list):
            children: list[Value] = []
            for child in contained:
                assert isinstance(child, dict)
                children.append(cls.required_resource_fields(child))
            result["contained"] = children
        return result

    @classmethod
    def questionnaire_fields(cls, value: Value) -> Value:
        """Replace obsolete options and supply required enableWhen operators in this fixture."""
        if isinstance(value, list):
            return [cls.questionnaire_fields(child) for child in value]
        if not isinstance(value, dict):
            return value
        result = {key: cls.questionnaire_fields(child) for key, child in value.items() if key != "options"}
        if isinstance(options := value.get("options"), dict):
            result["answerValueSet"] = options["reference"]
        if isinstance(conditions := result.get("enableWhen"), list):
            for condition in conditions:
                assert isinstance(condition, dict)
                condition["operator"] = "="
        return result


@pytest.mark.parametrize("release", ["r4b", "r5"])
def test_legacy_patient_queries_on_valid_native_patient(release: str) -> None:
    """Forty Patient scenarios retain their features with native choices and explicit predicate/functions."""
    root = Path(__file__).parents[1]
    suite = FixtureSuite.from_file(root / "cases/simple.yaml")
    assert isinstance(suite.subject, dict)
    payload = dict(suite.subject)
    deceased = payload.pop("deceased")
    assert isinstance(deceased, dict)
    payload["deceasedBoolean"] = deceased["boolean"]
    native = CanonicalInput.from_payload(payload, release)
    count = 0
    for case, _ in suite.cases():
        if case.input_file is not None:
            continue
        if isinstance(case.expression, str) and case.expression == "Patient.name.exists(given)":
            with pytest.raises(FHIRPathError, match="singleton"):
                evaluate(native.value, case.expression)
            case = case.model_copy(update={"expression": "Patient.name.exists(given.exists())"})
        if (
            isinstance(case.expression, str)
            and case.expression == "Patient.name.given.select($this.length) = Patient.name.given.select(length)"
        ):
            assert evaluate(native.value, case.expression) == []
            case = case.model_copy(
                update={"expression": "Patient.name.given.select($this.length()) = Patient.name.given.select(length())"}
            )
        count += native.check(case, root / "resources")
    assert count == 40


@pytest.mark.parametrize("release", ["r4b", "r5"])
def test_legacy_choice_paths_on_valid_native_resources(release: str) -> None:
    """Every nested choice path works with the required Observation/QuestionnaireResponse fields."""
    root = Path(__file__).parents[1]
    suite = FixtureSuite.from_file(root / "cases/3.2_paths.yaml")
    assert isinstance(suite.subject, dict)
    native = CanonicalInput.from_payload(CanonicalInput.required_resource_fields(suite.subject), release)
    count = 0
    for case, _ in suite.cases():
        if case.description == "Observation.value without a model":
            case = case.model_copy(update={"expected": ["high"]})
        count += native.check(case, root / "resources")
    assert count == 19


@pytest.mark.parametrize("release", ["r4b", "r5"])
def test_legacy_repetition_on_valid_native_questionnaire(release: str) -> None:
    """Repetition retains every original linkId after correcting obsolete Questionnaire fields."""
    root = Path(__file__).parents[1]
    suite = FixtureSuite.from_file(root / "cases/5.2.3_repeat.yaml")
    payload = CanonicalInput.questionnaire_fields(suite.subject)
    assert isinstance(payload, dict)
    native = CanonicalInput.from_payload(payload, release)
    assert sum(native.check(case, root / "resources") for case, _ in suite.cases()) == 2


@pytest.mark.parametrize("release", ["r4b", "r5"])
def test_legacy_quantity_choices_on_valid_native_response(release: str) -> None:
    """Quantity conversion and type selection work when answer uses its required array shape."""
    root = Path(__file__).parents[1]
    payload = _PAYLOAD.validate_json((root / "resources/quantity-example.json").read_bytes())
    assert isinstance(rows := payload["item"], list)
    for row in rows:
        assert isinstance(row, dict)
        row["answer"] = [row["answer"]]
    payload.update(status="completed", questionnaire="http://example.org/questionnaire")
    native = CanonicalInput.from_payload(payload, release)
    count = 0
    for filename in ("6.3_types.yaml", "fhir-quantity.yaml"):
        for case, _ in FixtureSuite.from_file(root / "cases" / filename).cases():
            if case.input_file != "quantity-example.json":
                continue
            if case.description == "After converting 'a' to year it isn't equal to 'a'":
                case = case.model_copy(update={"expected": []})
            count += native.check(case, root / "resources")
    assert count == 9


@pytest.mark.parametrize("release", ["r4b", "r5"])
def test_supply_duration_on_valid_native_medication_request(release: str) -> None:
    """Missing resource requirements do not prevent native Duration conversion."""
    root = Path(__file__).parents[1]
    payload = _PAYLOAD.validate_json((root / "resources/medicationrequest-example.json").read_bytes())
    payload.update(subject={"reference": "Patient/example"}, status="active", intent="order")
    if release == "r5":
        payload["medication"] = {"concept": {"text": "fixture"}}
    else:
        payload["medicationCodeableConcept"] = {"text": "fixture"}
    native = CanonicalInput.from_payload(payload, release)
    cases = [
        case
        for case, _ in FixtureSuite.from_file(root / "cases/5.5_conversion.yaml").cases()
        if case.input_file == "medicationrequest-example.json"
    ]
    assert sum(native.check(case, root / "resources") for case in cases) == 1


@pytest.mark.parametrize("release", ["r4b", "r5"])
def test_quantity_fragment_with_required_link_id(release: str) -> None:
    """A native fragment keeps the same quantity assertion once linkId is supplied."""
    root = Path(__file__).parents[1]
    payload = _PAYLOAD.validate_json((root / "resources/questionnaire-part-example.json").read_bytes())
    cases = [
        case
        for case, _ in FixtureSuite.from_file(root / "cases/simple.yaml").cases()
        if case.input_file == "questionnaire-part-example.json"
    ]
    [case] = cases
    assert isinstance(case.expression, BoundExpression)
    with pytest.raises(ValidationError):
        case.expression.validate_input(payload, release)
    payload["linkId"] = "fixture"
    native = CanonicalInput(value=case.expression.validate_input(payload, release))
    assert native.check(case.model_copy(update={"release": release}), root / "resources") == 1


@pytest.mark.parametrize("release", ["r4b", "r5"])
def test_valueset_repetition_with_valid_native_identifier(release: str) -> None:
    """A representable expansion URI leaves recursive contains traversal unchanged."""
    root = Path(__file__).parents[1]
    payload = _PAYLOAD.validate_json((root / "resources/valueset-example-expansion.json").read_bytes())
    assert isinstance(expansion := payload["expansion"], dict)
    expansion["identifier"] = "http://example.org/expansion/fixture"
    native = CanonicalInput.from_payload(payload, release)
    cases = [
        case
        for case, _ in FixtureSuite.from_file(root / "cases/fhir-r4.yaml").cases()
        if case.input_file == "valueset-example-expansion.json"
    ]
    assert sum(native.check(case, root / "resources") for case in cases) == 1


class CompleteExtension(Extension):
    """A Pydantic profile restores the primitive companion absent from the vendor Extension."""

    valueString__ext: FHIRPrimitiveExtension | None = Field(default=None, alias="_valueString")


class CompleteR4BExtension(R4BExtension):
    """The same explicitly declared companion works with R4B metadata."""

    valueString__ext: R4BPrimitiveExtension | None = Field(default=None, alias="_valueString")


@pytest.mark.parametrize("release", ["r4b", "r5"])
def test_extension_only_choice_primitive_on_typed_profile(release: str) -> None:
    """An explicit validated companion supports absent primitive values and value.id navigation."""
    root = Path(__file__).parents[1]
    extension_type = CompleteExtension if release == "r5" else CompleteR4BExtension
    primitive_type = FHIRPrimitiveExtension if release == "r5" else R4BPrimitiveExtension
    extension = extension_type.model_validate({"url": "test", "_valueString": {"id": "testing"}})
    companion = primitive_type.model_validate({"extension": [extension]})
    native = CanonicalInput.from_payload(
        {"resourceType": "Patient", "communication": [{"language": {"text": "Dutch"}, "_preferred": companion}]},
        release,
    )
    cases = [
        case
        for case, _ in FixtureSuite.from_file(root / "cases/extensions.yaml").cases()
        if case.input_file == "patient-example-2.json"
    ]
    assert sum(native.check(case, root / "resources") for case in cases) == 2
    assert evaluate(extension, "value.id") == ["testing"]
    assert extension.valueString is None


@pytest.mark.parametrize("release", ["r4b", "r5"])
def test_official_subset_with_valid_native_benefit(release: str) -> None:
    """The official subset expression works after supplying required benefit resource fields."""
    root = Path(__file__).parents[1]
    payload = _PAYLOAD.validate_json((root / "hl7/r5/explanationofbenefit-example.json").read_bytes())
    payload.update(
        status="active",
        use="claim",
        outcome="complete",
        type={"text": "fixture"},
        created="2024-01-01",
        patient={"reference": "Patient/example"},
        provider={"reference": "Organization/provider"},
        insurer={"reference": "Organization/insurer"},
        insurance=[{"focal": True, "coverage": {"reference": "Coverage/example"}}],
    )
    assert isinstance(rows := payload["item"], list)
    for row in rows:
        assert isinstance(row, dict)
        row["productOrService"] = {"text": "fixture"}
    native = CanonicalInput.from_payload(payload, release)
    assert evaluate(
        native.value,
        "supportingInfo.where(category.coding.code = 'additionalbodysite').sequence.subsetOf($this.item.informationSequence)",
    ) == [True]


@pytest.mark.parametrize("release", ["r4", "r4b", "r5"])
def test_official_primitive_types_with_representable_uuid(release: str) -> None:
    """Native parameter type identity works with the UUID version supported by the vendor."""
    root = Path(__file__).parents[1]
    original = (root / f"hl7/{release}/parameters-example-types.xml").read_bytes()
    model = (r5_model if release == "r5" else r4b_model)("Parameters")
    with pytest.raises(ValidationError, match="UUID version 4"):
        model.model_validate_xml(original)
    corrected = original.replace(b"79a14950-442c-11ed-b878-0242ac120002", b"79a14950-442c-41ed-b878-0242ac120002")
    native = model.model_validate_xml(corrected)
    for expression in (
        "Parameters.parameter[0].value.is(FHIR.string)",
        "Parameters.parameter[1].value.is(FHIR.integer)",
        "Parameters.parameter[2].value.is(FHIR.uuid)",
        "Parameters.parameter[2].value.is(FHIR.uri)",
        "Parameters.parameter[3].value.is(FHIR.decimal)",
    ):
        assert evaluate(native, expression) == [True], expression
