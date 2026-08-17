# openzyme-tools

This package retains shared, non-authoritative tool resources. The former runner catalog,
command compiler, declared-output contracts, execution registry, and compatibility import
surface have been removed.

Current external execution is owned by revision-bound Host and runner services. Scientific
calculations live in `openzyme-pipeline`; model-visible control-plane tools live in
`openzyme-core`.
