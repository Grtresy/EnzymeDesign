# openzyme-domain

Shared OpenZyme domain enums and V3 control-plane contracts.

## Scope

This package owns stable vocabulary used across Host API, UI, CLI, core services,
capability engines, research adapters, and execution adapters.

## Core objects

Top-level product state is defined in `openzyme_domain.control_plane`:

- `Session`
- `Task`
- `Lane`
- `ApprovalRequest`
- `InboxMessage`
- `MemoryEntry`
- `AgentMember`
- `AgentRuntimeSignal`
- `EngineInvocation`
- `RunRecord`
- `SessionArtifactRecord`
- `SessionReportDraftRecord`
- `SessionReportRecord`

Shared enums such as `ArtifactKind`, `RunStatus`, and `SourceRefKind` remain in
`openzyme_domain.models` because they are consumed by multiple capability
packages.
