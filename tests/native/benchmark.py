"""Run with mise run benchmark; timings are measurements, never test thresholds."""

from statistics import median
from timeit import repeat

from fhir.resources.patient import Patient
from fhirpathpy import compile as upstream_compile

from fhirpath_pydantic import compile
from fhirpath_pydantic.types import Value


def main() -> None:
    """Compare compiled native queries with dump-plus-compiled-upstream queries."""
    expression = "Patient.name.where(use = 'official').given.first()"
    native = compile(expression, output_type=str)
    upstream = upstream_compile(expression)
    for count in (1, 100, 1000):
        # Literal values are the benchmark's equality predicate and expected result.
        resource = Patient.model_validate({"name": [{"use": "official", "given": ["benchmark"]}] * count})

        def baseline(resource: Patient = resource) -> list[Value]:
            return upstream(resource.model_dump(by_alias=True, exclude_none=True))

        def direct(resource: Patient = resource) -> list[str]:
            return native(resource)

        assert direct() == baseline() == ["benchmark"]
        native_us = median(repeat(direct, number=50, repeat=3)) * 20_000
        upstream_us = median(repeat(baseline, number=50, repeat=3)) * 20_000
        print(
            f"{count:4} names: native={native_us:.1f}µs dump+upstream={upstream_us:.1f}µs ratio={upstream_us / native_us:.2f}x"
        )


if __name__ == "__main__":
    main()
