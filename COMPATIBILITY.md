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

## Typed input boundaries

Public evaluation, compiled query methods, context bindings and fluent literals
accept `InputValue`, whose sequence and mapping arms are readonly and covariant.
A `list[Patient]` does not need a cast to `list[Value]`. Pydantic normalizes tuples
and readonly mappings into internal container shapes. Native resource objects
retain identity and are neither iterated as collections nor revalidated. These
contracts are checked by strict ty/Pyright and `test_inputs.py`, including a model
validator counter and a resource iterator that raises if called. Query focus is
constructed once per invocation.

## Baseline registry coverage

`test_registry.py` reads the installed, pinned 2.2.4 registry without executing its
untyped definitions. It requires all 87 callable function names to return from at
least one actual invocation in the native evaluator. It runs the complete YAML
corpus and a native identity-preserving exclusion probe. The other 24 registry
entries describe operators or internal operator aliases. This checks dispatch
coverage; it does not claim that every assertion or edge case passes. The same
audit discovers all five upstream unit-conversion families and exercises every
pair, including plural calendar aliases, with native precision-aware round trips.

Numeric functions preserve strict native output types: Integer `abs()` stays an
Integer, Decimal `abs()` retains every digit, and `round()` preserves the integer
part independently of the caller's Decimal context. Variadic `coalesce()` has no
fixed upper argument limit and the fluent form does not render arguments as text.
Finite Decimal arithmetic and unit scaling expand local precision as needed;
nonterminating division remains a Decimal approximation. Quantity negation and
rendering preserve long magnitudes. Native temporal conversion and fractional
arithmetic retain submicrosecond precision and do not collapse distinct times
under a caller's low Decimal precision. Ordered aggregates compare the declared
FHIR primitive value, so partial native dates cannot silently become strings.

## Reproducible audit evidence

| Corpus | Assertions | Passed | Failed | Unsupported | Input rejected | Upstream disabled |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original fhirpathpy YAML | 1,545 | 1,387 | 13 | 0 | 75 | 70 |
| Official HL7 R4/R4B/R5 XML | 3,613 | 2,857 | 31 | 690 | 35 | 0 |

Run `mise run parity` and `mise run parity:hl7` to reproduce the complete JSON
reports under `dist/`. Both commands currently exit nonzero. Error assertions
execute their expressions. Unsupported functions cannot count as expected errors.
The official fixtures are pinned and digest-verified; provenance and licensing
are in `tests/hl7/README.md` and `tests/hl7/sources.json`.

The original YAML corpus includes malformed synthetic FHIR resources and a
fragment without required `linkId`; those reject during native validation.
Some remaining YAML differences are intentional native behavior: declared FHIR
primitive identity, full native timestamp precision, and calendar year/month
uncertainty against mean UCUM durations. A legacy assertion also expects `System.Patient` to return false; the
native evaluator rejects that unresolved type name (`FHIR.Patient` is valid).
Three more legacy assertions use the old grammar precedence. Native `is` and `as`
bind after arithmetic and before union or comparison, as specified by the
[normative precedence table](https://hl7.org/fhirpath/N1/index.html).
The synthetic `Functions` resource also lacks native FHIR choice metadata for
nested extension values. Its native R4B/R5 equivalent is covered in
`test_boundaries.py`, including chained extension choice values and ids.
All 44 result/error differences have individual executable native expectations in
`test_reviewed_differences.py`. The tests evaluate every original case, check each
failed expression against its reviewed result or domain error, and require the
exact occurrence counts and raw status totals. A fixed evaluation clock makes
microsecond-format decisions reproducible. These checks do not rewrite fixtures,
reclassify audit results, or claim full HL7 conformance.

| Reviewed behavior | YAML differences | HL7 differences | Native decision |
| --- | ---: | ---: | --- |
| Calendar versus mean UCUM year | 1 | 0 | Equality and inequality are indeterminate without explicit conversion |
| Timestamp formatting | 2 | 0 | Preserve native microseconds |
| Type-operator precedence | 3 | 0 | Bind type tests before union and comparison |
| FHIR primitive identity | 1 | 3 | Retain declared id/code identity separately from System.String |
| Date and fractional-second arithmetic | 1 | 2 | Support native calendar addition and preserve fractions |
| Synthetic extension choice metadata | 1 | 0 | Use validated native R4B/R5 extensions; both analogues are regression-tested |
| Partial date comparison | 3 | 0 | Missing time precision remains indeterminate |
| Unknown System.Patient target | 1 | 3 | Raise a domain error; FHIR.Patient is the valid target |
| Native Time offsets | 0 | 6 | Accept representable offsets as an explicit extension |
| Unanchored calendar comparisons | 0 | 9 | Apply current FHIRPath conversion factors |
| Native choice field aliases | 0 | 3 | Expose valueQuantity alongside the value choice group |
| Distinct result ordering | 0 | 5 | Preserve first occurrences; normative order is unspecified |

Rejected native inputs and unsupported newer features remain separate audit
categories; the review gate does not turn them into successful evaluations.

The newer official corpus also exercises features absent from the 2.2.4 baseline,
including `lowBoundary`, `highBoundary`, `precision`, `sort`, `defineVariable`,
`matchesFull`, `escape`, `unescape`, terminology/profile functions, and specialized
static, document, HTML and CDA evaluation modes. These remain unsupported rather
than silently emulated. Unknown type names raise errors, including on empty
inputs. Fluent `of_type()` filters retain the actual Pydantic class. Distinctness
propagates indeterminate equality, such as comparing dates with different
precision; it does not classify those items as definitely unique.

The pinned R5 corpus expects last-occurrence ordering for several `distinct()`
assertions. This evaluator retains first occurrences; the
[normative specification](https://hl7.org/fhirpath/N1/index.html) does not guarantee
an order. These differences remain visible in the report.

Escaped member/function/type/variable names and extension-only primitive scalar propagation
have native regression coverage in `test_syntax.py` and `test_boundaries.py`.
Quantity `abs()`, native unit-text comparisons, conditional receiver cardinality
and compile-time Unicode escape validation also have regression coverage.

Regex operations use Python Unicode single-line semantics. Substitutions support
`$1`, `${1}` and `${name}` (with Python `(?P<name>...)` capture syntax), preserve
literal backslashes, and report malformed patterns or group references as
`FHIRPathError`. Empty regex replacement leaves the input unchanged.

Standard FHIR variables `%sct`, `%loinc` and `%ucum`, together with quoted
`vs-[id]` and `ext-[id]` variable names, resolve without caller configuration. Explicit bindings take
precedence and remain call-local. See `test_variables.py` and the
[FHIR environment variable definitions](https://hl7.org/fhir/fhirpath.html).

Fractional-second DateTime arithmetic preserves the fractional value. The pinned
R5 suite expects this; the older R4/R4B suites expect fractional seconds to be
truncated for one assertion. Both historical mismatches remain visible in the
report rather than changing native arithmetic or rewriting the upstream fixtures.

DateTime comparison does not assume a timezone for an offset-free time. When
only one time has an offset, equality and ordering are indeterminate; equivalence
is false. Two offset-free times compare as wall clocks, and two known offsets
normalize together. Native Python offsets containing seconds or microseconds are
rejected by temporal operations rather than silently truncated to minutes. Whole-minute
offsets retain their exact value, including the supported ±14-hour limits.
`test_native_subminute_offsets_are_rejected` and `test_native_minute_offsets_round_trip`
exercise both native DateTime and Time inputs. `join()` propagates empty input, preserves populated empty
strings, and omits extension-only primitive slots from the joined scalar values.

Unanchored calendar quantities use the normative conversion factors (one year
can convert to 12 months or 365 days). Several pinned historical assertions
expect these cross-unit comparisons to be indeterminate; the native tests retain
the documented conversion behavior. Fixed UCUM durations (`wk`, `d`, `h`, `min`,
`s`, `ms`) support native date/time arithmetic and compare interchangeably with
corresponding calendar units. Mean UCUM years/months are indeterminate against
calendar years/months unless explicitly converted, and may be equivalent. Calendar
quantity strings use calendar literal syntax without UCUM quotes. These policies
follow the [current Quantity definitions](https://hl7.org/fhirpath/en/index.html).

The fluent `binary()` method accepts the checked `BinaryOperator` type, so numeric,
quantity and temporal operations do not require rendering operands into query text.
The native arithmetic regression test rejects any attempt to invoke the parser.

## Unit and execution boundaries

Known units support mass, length, volume, calendar/definite time, products and
quotients. Other unit codes remain opaque and exact-match only. This is not a
complete UCUM catalogue or UCUM validation service. Native FHIR quantities without
UCUM codes can compare magnitudes when their unit text matches exactly (including
two quantities with no unit). This comparison does not enable System.Quantity
conversion or arithmetic on display labels. Missing magnitudes and incompatible
labels remain indeterminate; comparator-bearing quantities cannot become exact.

Evaluation does not serialize input models, mutate caller data, or perform implicit
network access. Resolution uses native Bundle/contained indexes before an explicit
caller callback. Tracing emits only to a supplied sink. Cached plans contain
syntax, field metadata and validators; evaluation inputs remain call-local.

`mise run check` enforces strict ty, strict Pyright, Ruff, architecture checks,
lock freshness and the native regression suite. Generated ANTLR Python is the only
runtime exclusion; its handwritten interfaces remain checked. `mise run build`
produces the wheel and source distribution, and `mise run benchmark` measures the
native path against dump-plus-compiled-upstream without hardware-specific gates.
