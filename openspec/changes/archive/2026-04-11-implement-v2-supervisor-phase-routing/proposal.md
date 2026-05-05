## Why

The blueprint makes the `Supervisor Graph` the top-level control plane for OpenZyme, but the current implementation still exposes separate Phase B and Phase C graph builders instead of one episode-scoped main graph. This leaves `research` and `design` as runnable subgraphs without the intended phase routing, unified resume semantics, or single Host entrypoint.

## What Changes

- Implement a real top-level supervisor graph for `intake`, `research`, `design`, and `execution`.
- Route phase transitions on one `episode_id` thread instead of selecting separate graph builders per Host or test entrypoint.
- Standardize canonical handoff between subgraphs so `research` feeds `design`, and `design` feeds `execution` without phase-local state leakage.
- Collapse Host and demo entrypoints onto one supervisor graph builder and one workflow command surface.
- Project phase progress and interrupts from the unified supervisor thread rather than from phase-specific ad hoc graph entrypoints.

## Capabilities

### New Capabilities
- `v2-supervisor-phase-routing`: Unified episode-scoped supervisor graph that routes `intake`, `research`, `design`, and `execution` through one Host entrypoint and one checkpoint thread.

### Modified Capabilities

## Impact

- Affected code: `packages/openzyme-graph`, `packages/openzyme-runtime`, `apps/openzyme-host-api`, local demo wiring, and graph/Host integration tests.
- Affected systems: LangGraph phase routing, Host command handling, workspace projection sourcing, and demo/runtime graph assembly.
- Dependencies: `v2-intake-execution-loop`, `v2-research-subgraph`, `v2-design-candidate-selection`, and the Phase A graph/runtime contracts.
