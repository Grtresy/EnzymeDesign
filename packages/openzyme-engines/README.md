# openzyme-engines

V3 capability engine bridge package for OpenZyme.

## Purpose

This package is the target home for V3 capability engines such as:

- `deep_research`
- `execution`
- `reporting`

## Boundary rule

- New V3 engine-facing product semantics should converge here.
- Engines may own capability-local execution state, but they must write product-visible state back through the V3 control plane.
