# v2-research-subgraph Specification

## Purpose
Define the design-internal research subgraph or tool contract used to collect evidence for the artifact-first design loop.
## Requirements
### Requirement: V2 implements a runnable research subgraph for the design loop
The system MUST implement a runnable `research` subgraph or equivalent graph-backed tool that can execute within the episode-scoped `design` workflow loop.

The initial research capability MUST:

- start from episode-scoped design-loop state
- execute research-specific logic without requiring a separate top-level `research` phase
- support a real search-backed research adapter, with Tavily as the first implementation
- persist progress using the shared runtime and checkpointer foundation
- produce canonical research outputs for later design iterations and report generation

#### Scenario: Design invokes research and receives normalized outputs
- **WHEN** the design loop invokes the research subgraph for an episode
- **THEN** the graph executes the research subgraph and persists research progress
- **THEN** the step can produce canonical research outputs for continued design work

#### Scenario: Research step uses the first concrete Tavily-backed adapter
- **WHEN** the design-owned research graph performs external search-backed research
- **THEN** it can execute through a Tavily-backed research adapter
- **THEN** the graph still consumes normalized outputs rather than Tavily-native response payloads

### Requirement: Research step supports bounded parallel research units and aggregation
The system MUST support bounded parallel research execution and an explicit aggregation step inside the research subgraph.

The first implementation MUST support at least:

- dispatching multiple research units in one research pass
- bounding the number of concurrent research units
- aggregating the results into normalized evidence-oriented outputs

#### Scenario: Research step fans out work and aggregates results
- **WHEN** the research supervisor identifies multiple research units to perform
- **THEN** the graph can dispatch bounded parallel worker execution for those units
- **THEN** a later aggregation step combines the worker outputs into structured research results

### Requirement: Research step writes normalized outputs into canonical evidence storage
The system MUST persist the public outputs of the research step through the canonical evidence foundation.

The persisted research output MUST include at least:

- evidence records or evidence refs
- source refs
- research summary
- unresolved gaps

#### Scenario: Research subgraph finishes with canonical outputs
- **WHEN** the research step completes successfully
- **THEN** normalized evidence-oriented outputs are written into canonical research storage
- **THEN** later design iterations, Host projections, and report review can consume them without reading worker-local graph buffers

#### Scenario: Tavily results are normalized before persistence
- **WHEN** the Tavily-backed research adapter returns search results
- **THEN** those results are normalized into canonical evidence records, source refs, research summary, and unresolved gaps before persistence
- **THEN** provider-native Tavily payloads are not required by downstream graph, Host, or UI layers

### Requirement: Research step surfaces recoverable interruptions through Host-facing projection seams
The system MUST expose recoverable research interruptions through the shared runtime and Host projection path.

The initial research interruption surface MUST support at least:

- recoverable failure handoff
- escalation
- optional clarification if the research step cannot continue safely

#### Scenario: Research step encounters a recoverable interruption
- **WHEN** the research subgraph hits a recoverable interruption or escalation condition
- **THEN** the graph persists that state on the episode thread
- **THEN** the Host projection layer can expose the interruption to clients without raw checkpoint decoding or pretending that the episode changed top-level phase
