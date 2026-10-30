# Official HL7 conformance fixtures

These are unchanged artifacts from
[FHIR/fhir-test-cases at db9fce391702b896c4e340dcb035ef44feb57093](https://github.com/FHIR/fhir-test-cases/tree/db9fce391702b896c4e340dcb035ef44feb57093).
The upstream Apache 2.0 license is preserved in `LICENSE.txt`.

`mise run fixtures:hl7` fetches the R4, R4B and R5 suites and every referenced
input, including the namespaced R5 corpus. `sources.json` records the upstream
path and SHA-256 of each artifact. The audit verifies these digests and requires
provenance for every input before evaluation.

`mise run parity:hl7` audits all 3,613 assertions. It writes
`dist/hl7-report.json` and exits nonzero while gaps remain. No feature category is
filtered out. Unsupported evaluation modes, static context declarations and
functions remain explicit findings; they never satisfy expected-error assertions.
XML resource inputs are validated with `fhir.resources.model_validate_xml`.
