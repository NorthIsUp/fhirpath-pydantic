# fhirpath-pydantic

This is our fork. Implement on a dedicated worktree branch and commit completed
changes before handing work back. Land verified commits on the default branch
through `origin` without pull requests. Keep the `upstream` remote read-only.

Implement analogous fhirpathpy feature parity for native `fhir.resources` models.
Use idiomatic Pydantic models, `RootModel`, model/field validators and validated
constructors. Runtime behavior belongs on its model owner. No module-level
private helper functions; public convenience functions remain thin wrappers.

Every signature is typed. Do not use `Any`, casts, or type suppression comments.
Strict ty, strict Pyright, tests, and hk must pass before pushing. Generated ANTLR
code is the only handwritten-runtime checking exclusion.

Use `mise run test`, `mise run lint`, `mise run format`, `mise run fix`,
`mise run benchmark`, and `mise run build`. Check `TODO.md` before related work.
