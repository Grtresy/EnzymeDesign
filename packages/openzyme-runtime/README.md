# openzyme-runtime

Shared runtime support utilities for OpenZyme.

## Scope

This package now contains cross-cutting runtime pieces that are not product-state
owners:

- settings and environment loading
- LLM factories, provider limits, and debug recording
- research tool wrappers
- HPC catalog interfaces
- Postgres checkpointer helpers for capability-local use
- small protocol/seam types consumed by engines and adapters

Canonical product state and migrations live in `packages/openzyme-core`.
Capability-specific behavior belongs in `packages/openzyme-engines` or the
provider package that owns the external integration.
