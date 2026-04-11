## Why

Phase C requires a real research phase, not just placeholder graph-state contracts. The repository currently has no LangGraph implementation that can fan out research work, compress results, and write normalized evidence outputs back into the canonical Phase C store.

## What Changes

- Implement the first runnable Phase C `research` subgraph.
- Add a supervisor-to-worker research flow that can fan out multiple research units and fan them back into a structured aggregation step.
- Introduce Tavily as the first concrete research search adapter, based on the already working `open_deep_research` configuration and runtime experience.
- Normalize research outcomes into canonical evidence, source refs, research summary, and unresolved gaps.
- Project research-phase progress and recoverable interruptions through the existing runtime and Host seams.

## Capabilities

### New Capabilities
- `v2-research-subgraph`: Runnable LangGraph research phase with parallel research units and canonical evidence output.

### Modified Capabilities

## Impact

- Affected code: `packages/openzyme-graph`, runtime graph assembly, Host projection loading, and research-related tests.
- Affected systems: LangGraph supervisor/subgraph execution, checkpointed phase progress, research adapter seams.
- Dependencies: `v2-research-evidence` foundation, Phase B runtime/checkpointer foundation, and the fixed graph phase contracts from Phase A.
