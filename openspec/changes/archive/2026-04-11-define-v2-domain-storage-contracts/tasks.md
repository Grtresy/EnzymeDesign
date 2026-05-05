## 1. Domain Contracts

- [x] 1.1 Define the Phase A core entity set, stable identifiers, and lifecycle enums for `Project`, `Episode`, `Decision`, `Approval`, `Run`, `ArtifactRecord`, and `ReportRecord`
- [x] 1.2 Document ownership boundaries between core business entities and deferred Phase C entities so later changes can extend without renaming the Phase A model

## 2. Storage Boundaries

- [x] 2.1 Specify which canonical records belong in the relational store and capture their required relationships
- [x] 2.2 Specify which durable execution fields belong only in the LangGraph checkpointer and which large objects belong only in the artifact store
- [x] 2.3 Define the stable identifier linkage rules across relational records, checkpoints, and artifact metadata

## 3. Cross-Change Alignment

- [x] 3.1 Align the domain and storage specs with the V2 blueprint and current mainline architecture document
- [x] 3.2 Record the dependency expectations that `define-v2-graph-state-contracts` and `define-v2-host-ui-contracts` will consume from this change
