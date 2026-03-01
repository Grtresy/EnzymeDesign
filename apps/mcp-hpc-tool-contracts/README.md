# mcp-hpc-tool-contracts

`mcp-hpc-tool-contracts` compiles domain-level adapter parameters into
`RunSpec` payloads and executes them through `mcp-hpc-runner`.

It provides:

- a compile API and CLI
- a run API and CLI (sync and async)
- an MCP stdio server that exposes each adapter as an MCP tool
- an opt-in integration smoke harness

## Covered adapters

- `hhblits`
- `chai_fold`
- `alphafold3`
- `colabfold`
- `fpocket`
- `tunnels`
- `vina`

## Quick start

From repo root:

```bash
uv --project apps/mcp-hpc-tool-contracts sync --extra dev
uv --project apps/mcp-hpc-tool-contracts run mcp-hpc-tool-contracts list-adapters
```

Compile only:

```bash
uv --project apps/mcp-hpc-tool-contracts run mcp-hpc-tool-contracts compile \
  --adapter hhblits \
  --params-json '{"query_fasta": "./fixtures/query.fasta", "db_prefix": "uniclust30"}' \
  --pretty
```

Compile + run via `mcp-hpc-runner`:

```bash
uv --project apps/mcp-hpc-tool-contracts run mcp-hpc-tool-contracts run \
  --adapter fpocket \
  --params-json '{"structure_path": "./fixtures/target.pdb"}' \
  --runner-config apps/mcp-hpc-runner/config/hpc_runner.toml \
  --pretty
```

Run MCP stdio server:

```bash
uv --project apps/mcp-hpc-tool-contracts run mcp-hpc-tool-contracts serve
```

## Integration smoke harness (opt-in)

Create a JSON payload map with one input set per adapter:

```json
{
  "hhblits": {"query_fasta": "./fixtures/query.fasta", "db_prefix": "uniclust30"},
  "chai_fold": {"input_fasta": "./fixtures/query.fasta"},
  "alphafold3": {"input_json": "./fixtures/af3_input.json"},
  "colabfold": {"input_fasta": "./fixtures/query.fasta"},
  "fpocket": {"structure_path": "./fixtures/target.pdb"},
  "tunnels": {"structure_path": "./fixtures/target.pdb", "mode": "detect"},
  "vina": {
    "receptor_path": "./fixtures/receptor.pdbqt",
    "ligand_path": "./fixtures/ligand.pdbqt",
    "center_x": 0,
    "center_y": 0,
    "center_z": 0,
    "size_x": 20,
    "size_y": 20,
    "size_z": 20
  }
}
```

Then run:

```bash
uv --project apps/mcp-hpc-tool-contracts run mcp-hpc-tool-contracts-integration \
  --params-file ./adapter-smoke-inputs.json \
  --runner-config apps/mcp-hpc-runner/config/hpc_runner.toml
```
