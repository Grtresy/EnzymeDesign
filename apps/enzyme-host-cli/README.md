# enzyme-host-cli

`enzyme-host-cli` provides the minimal local Host CLI/runtime described in the
OpenSpec change.

## MVP command surface

From an initialized project workspace:

```bash
enzyme init demo-project
cd demo-project
enzyme new-episode "improve binding for substrate X"
enzyme plan import ./plan.json
enzyme run
enzyme status
enzyme logs <run_id>
enzyme report
```

Supported commands:

- `enzyme init <name>`
- `enzyme new-episode "<goal>"`
- `enzyme plan import <plan-file>`
- `enzyme plan confirm [plan-file]`
- `enzyme run [--step <step_id> | --resume]`
- `enzyme status`
- `enzyme logs <run_id>`
- `enzyme report`

## Plan format

The runtime persists the canonical plan in `episodes/<episode_id>/plan.yaml` via
the `mcp-project-memory` store. For the MVP, the CLI accepts structured plan
files encoded as JSON objects. The canonical file keeps the historical
`plan.yaml` name because that is the workspace contract exposed by
`mcp-project-memory`.

Example:

```json
{
  "steps": [
    {
      "id": "pocket_1",
      "tool": "fpocket",
      "inputs": {
        "pdb": "data/inputs/target.pdb"
      }
    }
  ]
}
```

Each step must include:

- `id`
- `tool`
- either `params` or `inputs`

`inputs` supports a small alias layer for the covered adapters. Relative paths
are resolved from the project root before the step is submitted through
`mcp-hpc-tool-contracts`.

## Local development

From the repo root:

```bash
uv --project apps/enzyme-host-cli sync --extra dev
uv --project apps/enzyme-host-cli run pytest
uv --project apps/enzyme-host-cli run enzyme --help
```
