# v2-research-subgraph Specification

## Purpose
TBD - created by archiving change implement-v2-research-subgraph. Update Purpose after archive.
## Requirements
### Requirement: V2 implements a runnable research subgraph for Phase C
The system MUST implement a runnable `research` graph phase that can execute within the episode-scoped V2 LangGraph workflow.

The initial research phase MUST:

- start from episode-scoped supervisor state
- execute research-specific logic within the `research` phase
- support a real search-backed research adapter, with Tavily as the first implementation
- persist phase progress using the shared runtime and checkpointer foundation
- produce canonical research outputs for later phases

#### Scenario: Episode enters and completes the research phase
- **WHEN** an episode transitions into the `research` phase
- **THEN** the graph executes the research subgraph and persists research-phase progress
- **THEN** the phase can produce canonical research outputs for downstream consumption

#### Scenario: Research phase uses the first concrete Tavily-backed adapter
- **WHEN** the Phase C research graph performs external search-backed research
- **THEN** it can execute through a Tavily-backed research adapter
- **THEN** the graph still consumes normalized outputs rather than Tavily-native response payloads

### Requirement: Research phase supports bounded parallel research units and aggregation
The system MUST support bounded parallel research execution and an explicit aggregation step in the Phase C research subgraph.

The first implementation MUST support at least:

- dispatching multiple research units in one research pass
- bounding the number of concurrent research units
- aggregating the results into normalized evidence-oriented outputs

#### Scenario: Research phase fans out work and aggregates results
- **WHEN** the research supervisor identifies multiple research units to perform
- **THEN** the graph can dispatch bounded parallel worker execution for those units
- **THEN** a later aggregation step combines the worker outputs into structured research results

### Requirement: Research phase writes normalized outputs into canonical evidence storage
The system MUST persist the public outputs of the research phase through the canonical evidence foundation.

The persisted research output MUST include at least:

- evidence records or evidence refs
- source refs
- research summary
- unresolved gaps

#### Scenario: Research subgraph finishes with canonical outputs
- **WHEN** the research phase completes successfully
- **THEN** normalized evidence-oriented outputs are written into canonical research storage
- **THEN** later phases and Host projections can consume them without reading worker-local graph buffers

#### Scenario: Tavily results are normalized before persistence
- **WHEN** the Tavily-backed research adapter returns search results
- **THEN** those results are normalized into canonical evidence records, source refs, research summary, and unresolved gaps before persistence
- **THEN** provider-native Tavily payloads are not required by downstream graph, Host, or UI layers

### Requirement: Research phase surfaces recoverable interruptions through Host-facing projection seams
The system MUST expose recoverable research interruptions through the shared runtime and Host projection path.

The initial research interruption surface MUST support at least:

- recoverable failure handoff
- escalation
- optional clarification if the research phase cannot continue safely

#### Scenario: Research phase encounters a recoverable interruption
- **WHEN** the research subgraph hits a recoverable interruption or escalation condition
- **THEN** the graph persists that state on the episode thread
- **THEN** the Host projection layer can expose the interruption to clients without raw checkpoint decoding

