# Artifacts

Use `artifacts` for all sandbox file inputs and outputs.

There are two artifact read surfaces:

- control-plane agent tools: `artifact.list`, `artifact.get`, `artifact.preview`, `artifact.read_text`, and `artifact.range`; these return safe session catalog records and bounded UTF-8 text content by `artifact_id`
- sandbox SDK: `openzyme_pipeline.artifacts`; this is available only inside the controlled execution sandbox and returns sandbox-safe paths for artifacts explicitly declared in `execution.pipeline.start.inputs.artifact_ids` / `context_artifact_ids`

Neither surface returns the Host-private `storage_uri`.

## Reading Inputs

```python
receptor = artifacts.get("art_receptor")
```

`artifacts.get()` only returns artifacts authorized for the current session, task, and lane. It returns a sandbox-safe artifact reference, not the host `storage_uri`. The `path` field is mounted under `/openzyme/input/...` and exists only inside the sandbox.

Expected fields on artifact references:

- `artifact_id`
- `path`
- `format`
- `kind`
- `title`
- `metadata`

## Registering Outputs

Only files under `/openzyme/output` or SDK-fetched outputs can be registered.

```python
artifacts.register(
    path="/openzyme/output/prepared_ligand.pdbqt",
    kind="structure",
    format="pdbqt",
    metadata={"purpose": "vina ligand input"},
)
```

For fetched HPC outputs:

```python
result = hpc.fpocket(structure_artifact_id=structure["artifact_id"])
for item in result.get("artifacts", []):
    print(item["artifact_id"])
```

Do not register arbitrary absolute host paths. Dry-run must reject them.

Pipeline code must not infer Host paths from workspace/API responses. Inputs must be authorized through the artifact catalog and staged by the Host supervisor; runner/HPC inputs must use staged sandbox or runner paths derived from that authorization.
