# enzyme-host-cli

`enzyme-host-cli` is the debug and automation surface for the shared host
runtime. The browser-based `enzyme-web-host` is now the main MVP operator entrypoint.

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
are resolved from the project root before execution.

Mixed-plan routing rules:

- `convert_format`, `smiles_to_3d`, `prepare_receptor`, and `prepare_ligand` run through the local preprocess executor
- `fpocket`, `hhblits`, `chai_fold`, `colabfold`, `alphafold3`, `tunnels`, and `vina` run through `mcp-hpc-tool-contracts`

Both routes write canonical step state and run manifests so `resume`, `status`,
the Web Host, and the CLI all observe the same lineage.

## Local development

From the repo root:

```bash
uv --project apps/enzyme-host-cli sync --extra dev
uv --project apps/enzyme-host-cli run pytest
uv --project apps/enzyme-host-cli run enzyme --help
```
