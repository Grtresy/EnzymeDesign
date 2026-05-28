# Artifacts

Use `artifacts` for explicit movement between the canonical artifact catalog and the executor sandbox.

The sandbox working copy is mutable. The artifact catalog is canonical and immutable/versioned. Files become canonical only when the executor registers outputs or snapshots source code.

There are two artifact read surfaces:

- control-plane agent tools: `artifact.list`, `artifact.get`, `artifact.preview`, `artifact.read_text`, and `artifact.range`; these return safe session catalog records and bounded UTF-8 text content by `artifact_id`
- sandbox SDK: `openzyme_pipeline.artifacts`; this is available only inside the controlled execution sandbox and returns sandbox-safe paths for artifacts explicitly authorized for the current session/task/lane

Neither surface returns the Host-private `storage_uri`, BlobStore path, sandbox host path, or runner path.

The storage model has two layers:

- Blob layer: Host-private sealed file/tree content addressed by `content_digest` or `tree_digest`.
- Artifact layer: immutable catalog records keyed by `artifact_id`, carrying kind/format, validation result, provenance, sealed digest, and workspace-facing `relative_path`.

`relative_path` is only a display/tree hint. Duplicate paths remain separate artifact leaves and must be distinguished by `artifact_id`.

## Materializing Inputs

```python
receptor_path = artifacts.materialize("art_receptor", target_path="/workspace/input/receptor.pdb")
```

`artifacts.materialize()` copies or maps an authorized artifact into the sandbox and returns a sandbox-safe path. The target must stay inside the allowed sandbox workspace/input area. Use this when the executor needs ordinary file operations before a pipeline run.

`artifacts.get()` remains available as a lightweight reference API for compatibility:

```python
receptor = artifacts.get("art_receptor")
```

It only returns artifacts authorized for the current session, task, and lane. It returns a sandbox-safe artifact reference, not the host `storage_uri`. Any `path` field exists only inside the sandbox.

Expected fields on artifact references:

- `artifact_id`
- `path`
- `format`
- `kind`
- `title`
- `metadata`

## Snapshotting Code

Source edited in `/workspace` is not canonical until it is snapshotted:

```python
source = artifacts.snapshot_code(
    paths="/workspace/src",
    entrypoint="/workspace/src/main.py",
    metadata={"semantic_type": "pipeline_source_snapshot"},
)
```

`snapshot_code` creates an immutable `ArtifactKind.CODE` record with `sandbox_workspace_id`, entrypoint, `source_tree_digest`, file digest manifest, and parent snapshot metadata. `sandbox.exec`, approvals, SDK operations, backend runs, and output provenance must bind to this snapshot. If the executor edits `/workspace/src` after a run starts, the existing run keeps its original snapshot; formal output from new source requires a new `sandbox.exec` / snapshot.

## Registering Outputs

Only files under `/workspace/output` or SDK-fetched outputs can be registered.

```python
artifacts.register(
    path="/workspace/output/prepared_ligand.pdbqt",
    kind="structure",
    format="pdbqt",
    metadata={"purpose": "vina ligand input"},
)
```

For fetched HPC outputs:

```python
from openzyme_pipeline import hpc, structure_tools

ws = hpc.workspace("fpocket")
remote_structure = ws.stage_artifact(
    structure["artifact_id"],
    workspace_path="inputs/structure.pdb",
)
run = structure_tools.fpocket(
    structure=remote_structure,
    placement=ws,
    expected_outputs=[
        {"path": "target_out", "kind": "directory", "format": "fpocket"},
    ],
)
result = ws.fetch_outputs(run, register=True)

for item in result.get("artifacts", []):
    print(item["artifact_id"])
```

Fetched outputs must be declared, fetched by the Host supervisor, and registered as artifact refs rather than exposed as private runner paths.

Registering performs a Host-supervised transaction: source digest/tree manifest, validator, temporary Blob write, sealed digest recheck, immutable Artifact row commit, and workspace manifest update. If validation, sealing, provenance, or commit fails, no visible artifact is created and the SDK receives a structured error.

Built-in validators always enforce non-empty output plus format checks for FASTA, HMM, CSV, JSON, and text-like outputs. `metadata.required_columns` can only tighten CSV validation; it cannot bypass the built-in validator.

Do not register arbitrary absolute host paths. Dry-run must reject them.

Pipeline code must not infer Host paths from workspace/API responses. Inputs must be authorized through the artifact catalog and staged/materialized by the Host supervisor; runner/HPC inputs must use staged sandbox or runner paths derived from that authorization.
