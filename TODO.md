# Remaining native baseline capabilities

- Support deferred-expression custom callback arguments. The original make_param(..., "Expr", ...) contract supplies callable arguments; native CustomFunction currently eagerly evaluates all arguments. Add a typed Pydantic macro call/argument API that preserves native focus, context and lexical scope without exposing mutable engine state.
- Support variadic custom callbacks. The original invocation metadata accepts variadic arguments; native CustomFunction currently uses only a finite tuple of arities. Add validated range/unbounded arity alongside the current closed sets, and exercise short-circuit/arity rejection before argument evaluation.

# Future extensions beyond the fhirpathpy 2.2.4 baseline

- Extend the unit catalogue and validation beyond the supported dimensional conversions; opaque unit codes currently remain exact-match only. Every original conversion family and unit pair has native regression coverage.
- Optional newer FHIRPath functions and specialized HL7 modes remain outside the baseline scope. COMPATIBILITY.md records their exact counts, and test_scope.py enforces that no unsupported function belongs to the pinned baseline.
