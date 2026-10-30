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

`evaluate(resource, expression, context=None)` returns a collection. Public inputs
use the covariant `InputValue` contract: concrete lists such as `list[Patient]`,
readonly sequences and mappings, and native models work without casts. Pydantic
normalizes container shapes at the boundary while preserving resource identity
and avoiding repeated resource validators. Context bindings and `literal()` use
the same contract. `compile`
creates a reusable query with `.first()` and cardinality-checking `.one()` helpers.
`compile_as_array` and `compile_as_first` additionally check the input model class.
`literal(value)` embeds a native constant in a fluent expression; `var(name)` binds
runtime data. Neither constructs or interpolates FHIRPath text.
`expression.binary(operator, other)` supports arithmetic, ordering, membership,
set and Boolean operators. Its `BinaryOperator` argument is statically typed and
validated with Pydantic; both operands remain native syntax nodes.
`is_type()`, `as_type()` and `of_type()` accept an actual Pydantic class or a
FHIR/System type name. For example, `path("gender").is_type("FHIR.string")` uses
the declared primitive hierarchy, while `path().as_type(Patient)` checks the real
model class and preserves the instance. Type names are syntax data and never
interpolated into a query string.

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

See [COMPATIBILITY.md](COMPATIBILITY.md) for measured feature coverage, audit
counts and remaining gaps.

## Supported scope

Version 0.1 implements native navigation, aliases, choices, primitive extensions,
variables, indexing, filtering, projection, repetition, aggregation, collection
operators, three-valued Boolean operators, numeric and string functions, native
scalar conversions, typed quantity literals/conversion/arithmetic, and
precision-aware temporal literals and comparisons. Unsupported functions raise `UnsupportedFeatureError`; there is no serialization fallback.

This is **not a drop-in implementation of every fhirpathpy feature**.
`type()` returns a typed `TypeInfo` model. Declared FHIR primitive subtypes are
retained separately from their Python representations: `type()` retains concrete primitive identity, while `is()`, `as()` and `ofType()`
recognize FHIR primitive specializations (for example, code specializes string
and uuid specializes uri). `is()` still distinguishes FHIR primitives from System
types; `ofType()` also supports implicit System conversion. `getValue()` returns the underlying System value. Raw dictionaries support ordinary fields; native choice
resolution requires FHIR models. Use R4B or R5 models for clinical resources.

Partial temporal results use the frozen `TemporalValue` Pydantic model; complete
values retain Python temporal types. Missing precision produces an indeterminate
comparison where required. Calendar arithmetic clamps month-end dates, retains
partial precision, and preserves fractional seconds. Fixed UCUM durations
(`wk`, `d`, `h`, `min`, `s`, `ms`) work as their corresponding calendar components.
Mean UCUM years/months (`a`, `mo`) require explicit conversion to calendar units. `literal(TemporalValue(kind="DateTime", year=2018))`
works without query text. Text literals also support partial DateTimes such as
`@2018T`, `@2018-02T`, and `@2018-02-02T`.

Quantity results use the frozen `QuantityValue` Pydantic model. Known conversions
cover mass, length, volume, time and their products/quotients. Other UCUM codes
remain opaque and exact-match only; this is not a complete UCUM catalogue. Native
FHIR quantities require a UCUM system and code for implicit conversion, and a
comparator cannot silently become an exact value. Calendar years/months remain
indeterminate against their mean UCUM counterparts, while fixed durations from
weeks through milliseconds are interchangeable; conversion uses Decimal without integer rounding. Quantity equivalence carries
input precision through unit conversion; exact equality and converted values
remain exact.

`EvaluationOptions` registers eager `CustomFunction` and deferred `CustomMacro`
definitions, a trace sink, and a native reference resolver. Handlers receive `FunctionCall` and return native
collections; trace sinks receive `TraceEvent`. Pass `options=` to `compile`,
`evaluate`, or the typed compile helpers. Registration, argument counts and return
boundaries are validated with Pydantic. Builtin overrides are supported.

`resolve()` indexes native Bundle entries and contained-resource scopes within one
evaluation, then consults the optional caller resolver. It preserves resource
identity and performs no implicit network access. An unconfigured `trace()` keeps
its input and produces no console output. FHIR model subclasses with their own
Pydantic validators retain their logical resource type.

The original `fhirpathpy/` source and original tests remain in this fork for
provenance. They are not shipped in the new wheel or included in its strict type
checks. Only the generated ANTLR implementation is excluded from type/lint checks
within `src`; its handwritten interface stubs are checked.

## Development

```sh
mise run sync
mise run check
mise run benchmark
mise run profile
mise run build
mise run smoke
```

`hk check --all` enforces Ruff, formatting, strict Pyright, `ty` with every rule set
to error, and lock freshness. Handwritten runtime and native tests contain no `Any`,
casts, or type suppression comments. The benchmark compares compiled native queries
against compiled fhirpathpy plus `model_dump(by_alias=True, exclude_none=True)`;
it reports timings without making hardware-dependent pass/fail claims.


`mise run parity` executes every original YAML scenario against native validated
resources and writes `dist/parity-report.json`. It exits nonzero while any enabled
case fails, uses an unsupported feature, lacks an expectation, or has an input
rejected by FHIR validation. Upstream-disabled cases remain visible. Error cases
are actually evaluated; an unsupported feature never satisfies an expected error.
The audit compares native models, quantities and temporal values with their
analogous expected values rather than requiring JSON-shaped results.

The source grammar is `grammar/FHIRPath.g4`. `mise run grammar` regenerates the
Python lexer and parser using the official ANTLR 4.13.2 JAR, verified by SHA-256.
Regeneration requires Java on the mise environment PATH.

`mise run parity:hl7` audits the complete pinned official R4/R4B/R5 XML corpora
using native FHIR model parsing. It records every assertion, including unsupported
configurations and rejected inputs, in `dist/hl7-report.json`.

`mise run smoke` builds the wheel, checks its typed package and grammar files,
and runs native queries and Pydantic constraints in a subprocess outside the
checkout. The probe requires its imports to come from the wheel archive, preserves
model identity and validator counts, and checks that the legacy engine is not
loaded. CI runs this check after the full native test and typing gate.

## Deferred and variadic callbacks

Use `CustomMacro` when the callback must choose which expressions evaluate.
An argument's `evaluate()` uses its bound FHIR focus and retains primitive
metadata, extensions, resource ownership, `$index` and `$total`. Supply
`evaluate(new_focus, index=...)` to evaluate per element; the original index
resolves duplicate scalar provenance. Explicit `None` means an empty focus.

```python
from pydantic import BaseModel, Field
from fhirpath_pydantic import CustomMacro, EvaluationOptions, FunctionArity, MacroCall
from fhirpath_pydantic.types import Collection

class ChoicePolicy(BaseModel):
    minimum_results: int = Field(default=1, ge=1, strict=True)

    def first_present(self, call: MacroCall) -> Collection:
        for argument in call.arguments:
            if len(result := argument.evaluate()) >= self.minimum_results:
                return result
        return []

policy = ChoicePolicy()
options = EvaluationOptions(functions=(
    CustomMacro(
        name="firstPresent",
        handler=policy.first_present,
        arity=FunctionArity(minimum=1),
    ),
))
```

A tuple such as `arity=(0, 2)` remains a closed set. `FunctionArity(minimum=1,
maximum=3)` accepts an inclusive range; omitting `maximum` permits unbounded
arguments. These forms work for eager functions and macros, and arity errors
occur before any argument evaluates. Pydantic registration dictionaries select
a macro with `kind="macro"`; the eager default is `kind="function"`. Unknown
registration/options fields are rejected rather than silently ignored.

Use a Pydantic schema or TypeAdapter inside the handler for scalar argument
constraints. Deferred arguments also expose `name` for identifier/type arguments
without evaluating a path. Callback results are native values: model identity is
preserved, and returned scalars have System types rather than inferred field
provenance. Generic callback state belongs to the caller; compiled plans never
cache a call's bound arguments or focus.
