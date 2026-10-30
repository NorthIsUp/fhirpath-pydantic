# Native compatibility status

The target is analogous fhirpathpy 2.2.4 functionality on validated
`fhir.resources` objects. Native models, Decimal values, dates, bytes and UUIDs
retain their Python representations. Invalid FHIR input is rejected at the
Pydantic boundary. JSON-shaped output and upstream implementation quirks are not
the compatibility contract.

The implementation is **not yet fully conformant**. The audits below report
remaining failures rather than converting them into passes or disabled tests.

## Implemented feature families

| Family | Native behavior | Verification |
| --- | --- | --- |
| Navigation | R4B/R5 aliases, choice groups, primitive extensions, collection traversal and identity | `test_native.py`, `test_boundaries.py` |
| Typed queries | Reusable compiled queries, strict result adapters, typed input helpers and string-free fluent expressions | `test_native.py`, `test_compatibility.py` |
| Validation | FHIRPath constraints integrate through Pydantic validators and preserve caller model invariants | `test_native.py`, `test_model_subclasses.py` |
| Primitive types | Declared FHIR subtypes, System values, `type()`, `is`, `as` and `ofType` | `test_type_metadata.py` |
| Collections | Filtering, projection, sets, indexing, repetition, aggregation and lexical argument scopes | `test_compatibility.py`, `test_utilities.py` |
| Scalars | Numeric functions, conversions, strings, encodings, Boolean logic and recursive equivalence | `test_boundaries.py`, `test_equivalence.py`, `test_utilities.py` |
| Quantities | Exact Decimal conversion, dimensional arithmetic and unit-aware comparison precision | `test_quantities.py` |
| Temporal values | Partial precision, offset comparison, calendar arithmetic and trailing-T DateTime literals | `test_temporal.py` |
| Extensions | Typed custom functions, trace sinks, scoped native references and optional resolver callbacks | `test_callbacks.py`, `test_resolution.py` |
| Model ownership | Runtime module functions delegate to Pydantic owners; private module helpers are banned | `test_architecture.py` |

All test filenames above are under `tests/native/`. Family coverage means the
feature exists and has regression coverage; it is not a claim that every edge
case in that family passes the official suites.

## Reproducible audit evidence

| Corpus | Assertions | Passed | Failed | Unsupported | Input rejected | Upstream disabled |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original fhirpathpy YAML | 1,545 | 1,382 | 18 | 0 | 75 | 70 |
| Official HL7 R4/R4B/R5 XML | 3,613 | 2,730 | 158 | 690 | 35 | 0 |

Run `mise run parity` and `mise run parity:hl7` to reproduce the complete JSON
reports under `dist/`. Both commands currently exit nonzero. Error assertions
execute their expressions. Unsupported functions cannot count as expected errors.
The official fixtures are pinned and digest-verified; provenance and licensing
are in `tests/hl7/README.md` and `tests/hl7/sources.json`.

The original YAML corpus includes malformed synthetic FHIR resources and a
fragment without required `linkId`; those reject during native validation.
Some remaining YAML differences are intentional native behavior: declared FHIR
primitive identity, full native timestamp precision, and calendar versus definite
durations. The outstanding failures still require case-by-case review.

The newer official corpus also exercises features absent from the 2.2.4 baseline,
including `lowBoundary`, `highBoundary`, `precision`, `sort`, `defineVariable`,
`matchesFull`, `escape`, `unescape`, terminology/profile functions, and specialized
static, document, HTML and CDA evaluation modes. These remain unsupported rather
than silently emulated. The report also exposes ordinary function edge cases that
still need correction, including escaped identifiers and extension-only primitives.

## Unit and execution boundaries

Known units support mass, length, volume, calendar/definite time, products and
quotients. Other unit codes remain opaque and exact-match only. This is not a
complete UCUM catalogue or UCUM validation service.

Evaluation does not serialize input models, mutate caller data, or perform implicit
network access. Resolution uses native Bundle/contained indexes before an explicit
caller callback. Tracing emits only to a supplied sink. Cached plans contain
syntax, field metadata and validators; evaluation inputs remain call-local.

`mise run check` enforces strict ty, strict Pyright, Ruff, architecture checks,
lock freshness and the native regression suite. Generated ANTLR Python is the only
runtime exclusion; its handwritten interfaces remain checked. `mise run build`
produces the wheel and source distribution, and `mise run benchmark` measures the
native path against dump-plus-compiled-upstream without hardware-specific gates.
