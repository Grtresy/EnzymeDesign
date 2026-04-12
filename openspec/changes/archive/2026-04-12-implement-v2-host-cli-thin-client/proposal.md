## Why

The blueprint makes CLI a secondary entrypoint that shares the same Host semantics as the web product, but the current V2 mainline has no CLI app. The only CLI code lives under `legacy/v1`, which is explicitly not the runtime baseline for V2.

## What Changes

- Add a new V2 Host CLI app that acts as a thin client over the current Host API.
- Expose the minimum episode command surface needed to create, resume, approve, reject, and inspect workflows from the terminal.
- Provide CLI read paths for workspace summaries, runs, artifacts, and reports so non-browser users can inspect workflow progress.
- Keep the CLI free of private runtime, graph, or checkpoint ownership; all workflow mutation remains mediated by Host API calls.

## Capabilities

### New Capabilities
- `v2-host-cli-thin-client`: V2 CLI application that consumes Host API commands and queries as a thin client instead of embedding a private workflow runtime.

### Modified Capabilities

## Impact

- Affected code: new `apps/openzyme-host-cli` surface, shared Host API client utilities, and CLI tests.
- Affected systems: local developer workflows, terminal-only workflow control, and command/query consistency across Web and CLI entrypoints.
- Dependencies: `v2-host-api`, `v2-workflow-streaming-api`, and `v2-report-review-workflow`.
