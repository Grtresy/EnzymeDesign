# OpenZyme V1 Legacy Workspace

This subtree preserves the frozen V1 Host stack after the repository hard cut
to the current V3 control-plane mainline.

Run all V1 commands from `legacy/v1`.

## Workspace Members

- `apps/enzyme-host-cli`
- `apps/enzyme-web-host`
- `apps/mcp-project-memory`
- `apps/mcp-preprocess`
- `apps/mcp-hpc-tool-contracts`
- `packages/enzyme-host-runtime`
- `packages/preprocess-backend`

The Node sidecar remains at `apps/pi-ai-sidecar`.

`apps/mcp-hpc-runner` was not copied into this subtree. V1 playgrounds and
tool-contract flows still reference the mainline runner at the repository root.

## Common Commands

```bash
uv sync
uv run pytest -m "not integration"
uv --project apps/enzyme-host-cli run enzyme --help
uv --project apps/enzyme-web-host run enzyme-web-host --project-root /path/to/project
uv --project apps/mcp-project-memory run mcp-project-memory --help
uv --project apps/mcp-preprocess run mcp-preprocess --help
uv --project apps/mcp-hpc-tool-contracts run mcp-hpc-tool-contracts list-adapters
```
