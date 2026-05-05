## Why

Phase B needs a product-facing Host layer that can create episodes, resume workflows, resolve approvals, and stream structured workflow updates to the UI. The repository currently has only Host API contracts; there is no FastAPI surface, no projection assembly, and no streaming transport over the Phase B runtime.

## What Changes

- Implement the first FastAPI Host surface for the V2 Phase B closed loop.
- Add query endpoints for episode workspace data and pending human actions.
- Add explicit commands for episode creation, approval resolution, and workflow resumption.
- Add a workflow-aware streaming endpoint that projects runtime and business changes into Host events.
- Implement projection assembly over canonical records and graph progress.

## Capabilities

### New Capabilities
- `v2-workflow-streaming-api`: Product-facing Host API for V2 workflow queries, commands, and streaming updates.

### Modified Capabilities

## Impact

- Affected code: `apps/openzyme-host-api`, runtime projection loaders, and FastAPI app wiring.
- Affected APIs: episode creation, resume, approval resolution, and workflow stream transport.
- Dependencies: runtime foundation and minimal graph loop changes.
