## Why

Phase B closes only when a user can actually create an episode, observe workflow progress, resolve approvals, and inspect execution outputs in a browser. The repository currently has UI read-model contracts only; there is no frontend project, no workspace shell, and no integration with the upcoming Host API and workflow stream.

## What Changes

- Create the first frontend project and tooling scaffold for `apps/openzyme-web-ui`.
- Implement the minimum episode workspace UI for the Phase B closed loop.
- Add workflow, pending-action, run, and artifact panels that consume Host projections.
- Add the minimum create/resume/approval interactions against the Host command surface.
- Subscribe the UI to Host workflow events and reflect live progress updates.

## Capabilities

### New Capabilities
- `v2-episode-workspace-ui`: Minimal Web UI for the Phase B episode workflow closed loop.

### Modified Capabilities

## Impact

- Affected code: `apps/openzyme-web-ui` frontend scaffold, API client layer, and workflow workspace components.
- Affected systems: browser product shell, Host API integration, workflow stream consumption.
- Dependencies: Host API and streaming change must land before full UI behavior can be validated.
