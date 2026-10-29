# fhirpath-pydantic

Native FHIRPath queries for `fhir.resources` 8.3, Pydantic v2, and Python 3.14.
Derived from [fhirpathpy 2.2.4](https://github.com/beda-software/fhirpath-py), retaining
its MIT-licensed ANTLR grammar and adding a fully typed native runtime.

```python
from fhir.resources.patient import Patient
from fhirpath_pydantic import compile, path, var

patient = Patient.model_validate({
    "name": [{"use": "official", "given": ["example"]}],
})
query = compile(
    "Patient.name.where(use = %use).given.first()",
    output_type=str,
)
assert query(patient, {"use": "official"}) == ["example"]

# Same operation without creating, escaping, or parsing a query string:
expression = (
    path("Patient", "name")
    .where(path("use").eq(var("use")))
    .field("given")
    .first()
)
assert compile(expression, output_type=str)(patient, {"use": "official"}) == ["example"]
```

`evaluate(resource, expression, context=None)` returns a collection. `compile`
creates a reusable query with `.first()` and cardinality-checking `.one()` helpers.
`compile_as_array` and `compile_as_first` additionally check the input model class.
`literal(value)` embeds a native constant in a fluent expression; `var(name)` binds
runtime data. Neither constructs or interpolates FHIRPath text.

Evaluation reads Pydantic fields directly. FHIR aliases (`Encounter.class`), choice
groups (`Observation.value`), and primitive extensions come from model metadata.
Selected models retain identity; dates, times, Decimals and bytes retain their
Python types. No `model_dump()`, JSON round trip, input mutation, or external FHIR
model table is used. R5 and R4B share the same reader. Cached plans contain syntax,
field metadata and validators; per-call variables stay out of caches.

## Pydantic invariants

```python
from typing import Annotated
from pydantic import BaseModel
from fhirpath_pydantic import FHIRPathConstraint

active = FHIRPathConstraint(
    expression="active = true",
    message="Resource must be active",
)

class Envelope(BaseModel):
    resource: Annotated[Patient, active.after_validator()]
```

Constraints require exactly `[True]`. Result adapters use strict Pydantic validation,
so a query declared as `str` cannot silently convert a Boolean or number. For
custom result schemas, `CompiledQuery(node=..., adapter=TypeAdapter[...](...))`
accepts an already-built adapter, including an `Annotated` type with validators.

## Supported scope

Version 0.1 implements native navigation, aliases, choices, primitive extensions,
variables, indexing, filtering, projection, repetition, aggregation, collection
operators, three-valued Boolean operators, numeric and string functions, native
scalar conversions, typed quantity literals/conversion/arithmetic, and
full-precision temporal literals. Unsupported functions raise `UnsupportedFeatureError`; there is no serialization fallback.

This is **not a drop-in implementation of every fhirpathpy feature**.
Partial-precision temporal arithmetic/comparison, `resolve()`,
`type()` metadata, and user invocation tables remain unsupported. Primitive subtype
checks currently use Python representations, so distinct FHIR string-derived types
are not distinguished. Raw dictionaries support ordinary fields; native choice
resolution requires FHIR models. Use R4B or R5 models for clinical resources.

Quantity results use the frozen `QuantityValue` Pydantic model. Known conversions
cover mass, length, volume, time and their products/quotients. Other UCUM codes
remain opaque and exact-match only; this is not a complete UCUM catalogue. Native
FHIR quantities require a UCUM system and code for implicit conversion, and a
comparator cannot silently become an exact value. Calendar durations remain
separate from definite units; conversion uses Decimal without integer rounding.

The original `fhirpathpy/` source and original tests remain in this fork for
provenance. They are not shipped in the new wheel or included in its strict type
checks. Only the generated ANTLR implementation is excluded from type/lint checks
within `src`; its handwritten interface stubs are checked.

## Development

```sh
mise run sync
mise run check
mise run benchmark
mise run build
```

`hk check --all` enforces Ruff, formatting, strict Pyright, `ty` with every rule set
to error, and lock freshness. Handwritten runtime and native tests contain no `Any`,
casts, or type suppression comments. The benchmark compares compiled native queries
against compiled fhirpathpy plus `model_dump(by_alias=True, exclude_none=True)`;
it reports timings without making hardware-dependent pass/fail claims.
