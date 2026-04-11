## Context

The Phase A domain and graph contracts already reserved extension space for evidence and research outputs, and Phase B introduced canonical persistence plus Host/UI projections for the minimum closed loop. What is still missing is a durable research/evidence model that can survive beyond a single graph run and can feed both the design phase and richer workspace views.

## Goals / Non-Goals

**Goals:**
- Define and persist the minimum Phase C research/evidence records needed by research and design.
- Keep research public outputs structured as evidence refs, summaries, and unresolved gaps rather than raw notes.
- Extend repository and Host projection seams so later changes can consume evidence through canonical interfaces.

**Non-Goals:**
- Implement the research subgraph itself.
- Implement candidate generation, comparison, or report generation.
- Introduce provider-specific external research integrations as part of this foundation.

## Decisions

### Add a dedicated Phase C research evidence capability instead of overloading Phase B execution records

Evidence and source refs have different ownership and query patterns than execution runs or artifacts. Treating them as first-class research records avoids leaking research semantics into execution tables and keeps design-phase inputs explicit.

Alternative considered: store research outputs only inside graph checkpoint state. Rejected because Host/UI and design logic need stable canonical records outside the checkpointer.

### Persist normalized research outputs rather than graph-internal note formats

The public Phase C interface will use normalized evidence records, source refs, research summary, and unresolved gaps. Internal `notes` or `raw_notes` forms may still exist inside graph workers later, but they are not canonical storage contracts.

Alternative considered: persist compressed free-text notes first and normalize later. Rejected because it would force downstream changes to parse unstable text blobs.

### Keep the evidence foundation provider-agnostic while allowing Tavily as the first adapter

The canonical evidence model should not expose Tavily-specific payload shapes, ranking fields, or response envelopes. The first concrete research adapter can still be Tavily, but it must normalize its outputs into `EvidenceRecord`, source refs, research summary, and unresolved gaps before they reach shared persistence or Host/UI layers.

Alternative considered: model canonical evidence storage directly around Tavily response objects. Rejected because it would couple Phase C storage contracts to one search provider and make later adapter expansion harder.

### Extend Host projection loading at the foundation layer, but keep richer pane behavior for a later change

This change adds repository-backed loading seams for research outputs so later Host/UI work can project them without re-opening storage decisions. It does not finalize richer workflow stream events or page layout.

Alternative considered: defer all projection support to the UI-focused change. Rejected because the graph and design changes also need the same canonical read path.

## Risks / Trade-offs

- [Risk] The first evidence schema may omit fields that a later research adapter wants to capture. → Mitigation: keep the normalized record focused on stable identifiers, source metadata, and structured summaries, with room for metadata extension.
- [Risk] Tavily-specific fields may leak into shared contracts during initial implementation. → Mitigation: require normalization at the research-adapter boundary and keep provider-native payloads in adapter-local code only.
- [Risk] Research summary ownership could overlap with future report records. → Mitigation: keep research summary scoped to research-phase output and leave final user-facing report semantics to Phase D.
- [Risk] Host projections may start depending on partially populated research data. → Mitigation: make empty evidence lists and absent research summary a valid, explicit state.

## Migration Plan

Add the Phase C research/evidence migration and repository layer, wire canonical loading into runtime and Host projection seams, and validate the new records with repository and projection tests before graph-level research logic is introduced.
