## Why

Phase B established a runnable intake-to-execution loop, but Phase C cannot add research or design behavior until research outputs have a canonical home outside transient graph-local fields. The repository still lacks durable evidence records, source references, and structured research summaries that later graph, Host, and UI layers can share.

## What Changes

- Implement the canonical Phase C research/evidence domain and persistence foundation.
- Add the minimum relational records and repositories for `EvidenceRecord`, source references, and structured research output.
- Extend runtime and projection seams so Host and later graph changes can read research outputs without traversing raw checkpoint payloads.
- Reserve the handoff surface consumed by the design phase, including research summary, unresolved gaps, and normalized source refs.
- Keep the canonical research/evidence model provider-agnostic so the first search adapter can be Tavily without leaking Tavily response shapes into shared contracts.

## Capabilities

### New Capabilities
- `v2-research-evidence`: Canonical research evidence, source reference, and summary persistence for Phase C.

### Modified Capabilities

## Impact

- Affected code: `packages/openzyme-domain`, `packages/openzyme-runtime`, `apps/openzyme-host-api`, and projection contracts consumed by the Web UI.
- Affected systems: relational storage, runtime repositories, Host workspace projection loading.
- Dependencies: existing Phase B runtime foundation and graph contracts; later Phase C graph and UI changes depend on this storage truth.
