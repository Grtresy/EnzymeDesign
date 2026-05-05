# openzyme-engines

V3 capability engine bridge package for OpenZyme.

## Purpose

This package is the target home for V3 capability engines such as:

- `deep_research`
- `execution`
- `reporting`

## Migration rule

- New V3 engine-facing product semantics should converge here.
- Existing V2-era packages such as `openzyme-graph`, `openzyme-research`, and `openzyme-execution` may still contain transitional code, but they should not become the long-term owner of V3 control-plane behavior.
