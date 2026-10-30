# Future extensions beyond the fhirpathpy 2.2.4 baseline

- Extend the unit catalogue and validation beyond the supported dimensional conversions; opaque unit codes currently remain exact-match only. Every original conversion family and unit pair has native regression coverage.
- Optional newer FHIRPath functions and specialized HL7 modes remain outside the baseline scope. COMPATIBILITY.md records their exact counts, and test_scope.py enforces that no unsupported function belongs to the pinned baseline.
