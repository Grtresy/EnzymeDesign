## Context

`apps/openzyme-web-ui` currently contains only contract notes and JSON read-model examples. There is no React app, no build toolchain, and no browser-facing workspace. Phase B needs a minimal but real product shell that proves the closed loop from episode creation to approval/resume and execution output visibility.

## Goals / Non-Goals

**Goals:**
- Create the first frontend project scaffold for V2.
- Render the minimum Phase B episode workspace using Host API query and stream data.
- Support create episode, resume, and approval resolution interactions from the browser.

**Non-Goals:**
- Build the final complete Web UI or report experience.
- Introduce LangSmith generative UI or browser-direct graph access.
- Optimize for all phases beyond the Phase B closed loop.

## Decisions

### Build the UI against Host query and stream contracts, not direct graph transport

This keeps the browser aligned to the architecture rule that Host is the shared entrypoint. The UI consumes Host read models and workflow events instead of raw LangGraph chunks or Agent Server hooks.

### Keep the first UI as a minimal episode workspace shell

The initial UI includes only the controls and panels required for the Phase B loop:
- episode creation
- workflow progress
- pending approval/interrupt visibility
- run list
- artifact list

Alternative considered: start from a more ambitious multi-page application shell. Rejected because Phase B only needs one closed-loop surface.

### Treat project bootstrapping as part of this change

Because `apps/openzyme-web-ui` has no actual frontend skeleton, project setup is part of the change rather than a prerequisite to it.

## Risks / Trade-offs

- [Risk] Frontend scaffolding may dominate the change before product behavior lands. → Mitigation: keep the first scaffold minimal and aligned only to the episode workspace.
- [Risk] UI may start shaping Host payloads indirectly. → Mitigation: keep a thin client layer that maps directly to the Host read-model contracts.
- [Risk] Streaming UX may be brittle before Host event shapes stabilize. → Mitigation: start this change after Host API streaming is available and keep event handling isolated.

## Migration Plan

Initialize the frontend project, add the episode workspace shell, wire it to Host queries and workflow events, and validate the minimum browser closed loop with component and integration-style tests where available.
