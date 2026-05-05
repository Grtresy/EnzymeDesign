# v2-research-evidence Specification

## Purpose
TBD - created by archiving change implement-v2-research-evidence-foundation. Update Purpose after archive.
## Requirements
### Requirement: V2 persists canonical research evidence records outside graph checkpoints
The system MUST persist Phase C research evidence in canonical business records outside LangGraph checkpoint payloads.

The initial canonical research record set MUST include:

- `EvidenceRecord`
- source references associated with an evidence record
- episode-scoped research summary output
- unresolved research gaps associated with an episode

#### Scenario: Host loads research evidence for an episode
- **WHEN** the Host or a later graph phase needs research outputs for an episode
- **THEN** it can load evidence records, source refs, research summary, and unresolved gaps from canonical persistence
- **THEN** it does not need to treat graph checkpoint payloads as the source of truth for research outputs

### Requirement: Research public outputs use normalized structured fields
The system MUST expose research public outputs through normalized structured fields rather than raw note formats.

The canonical research output shape MUST support at least:

- evidence identifiers and evidence summaries
- source provenance or locator fields
- a research summary for downstream phase consumption
- unresolved gaps that remain after the research pass

#### Scenario: Design phase consumes research output
- **WHEN** the design phase reads research results for an episode
- **THEN** it receives structured research summary, evidence refs, and unresolved gaps
- **THEN** it does not need to parse `raw_notes`, `notes`, or equivalent graph-internal text blobs

### Requirement: Research evidence records remain queryable through shared runtime seams
The system MUST expose research evidence through shared runtime and Host loading seams so later Phase C changes reuse one canonical access path.

The shared loading surface MUST support at least:

- listing evidence for an episode
- loading source refs associated with evidence
- loading research summary and unresolved gaps for an episode

#### Scenario: Later Phase C changes reuse canonical research loading
- **WHEN** the research subgraph, design phase, or Host projection layer needs research evidence
- **THEN** it uses shared runtime or repository seams for canonical access
- **THEN** package-local ad hoc evidence loading logic is not required

