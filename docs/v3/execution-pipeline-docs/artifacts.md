# Artifacts

Use `artifacts` for all file inputs and outputs.

## Reading Inputs

```python
receptor = artifacts.get("art_receptor")
```

`artifacts.get()` only returns artifacts authorized for the current session, task, and lane. It returns a sandbox-safe artifact reference, not the host `storage_uri`.

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
