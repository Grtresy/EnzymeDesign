# openzyme-domain

V2 typed contracts for OpenZyme core business entities.

## Scope

This package defines the Phase A canonical entity vocabulary shared by:

- `packages/openzyme-graph`
- `packages/openzyme-storage`
- `apps/openzyme-host-api`
- `apps/openzyme-web-ui`
- `packages/openzyme-execution`

## Core entities

- `Project`
- `Episode`
- `Decision`
- `Approval`
- `Run`
- `ArtifactRecord`
- `ReportRecord`

## Key rules

- `Episode` is the workflow business anchor.
- `thread_id = episode_id` in later graph contracts.
- Each core entity uses a stable object identifier rather than filesystem paths.
- Later Phase C entities such as `EvidenceRecord` and `CandidateRecord` extend the model by referencing existing IDs instead of reshaping the Phase A core set.
