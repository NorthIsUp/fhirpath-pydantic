# Remaining FHIRPath compatibility

- Extend the unit catalogue and unit validation beyond the supported dimensional conversions; opaque codes currently remain exact-match only.
- Implement partial-precision dates/times with FHIRPath indeterminate comparisons.
- Retain declared FHIR primitive subtypes separately from their Python representation.
- Add reference resolution through an explicit caller-provided resolver.
- Add `type()` metadata and typed custom-function registration.
- Run the complete HL7 conformance suite and publish a supported-feature matrix.

- Implement the remaining upstream utilities (`trace`, `trim`, `encode`, `decode`) and aggregate functions (`sum`, `avg`, `min`, `max`).
- Move remaining public scalar/collection helper implementations onto model owners; keep only thin API facades.
