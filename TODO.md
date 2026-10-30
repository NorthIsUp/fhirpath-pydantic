# Remaining FHIRPath compatibility

- Extend the unit catalogue and unit validation beyond the supported dimensional conversions; opaque codes currently remain exact-match only.
- Implement calendar arithmetic for native and partial-precision dates/times; precision-aware comparison is implemented.
- Extend the inherited grammar to accept date-only DateTime literals with a trailing `T` (currently supported through conversions and native literals).
- Retain declared FHIR primitive subtypes separately from their Python representation.
- Add `type()` metadata with declared FHIR primitive subtype tracking.
- Run the complete HL7 conformance suite and publish a supported-feature matrix.

- Move remaining public scalar/collection helper implementations onto model owners; keep only thin API facades.
