# Batch Patterns

Batch pipelines are allowed when they stay within approval and quota limits.

Use a simple loop and let each `hpc.*` call create a separate supervised run:

```python
from openzyme_pipeline import artifacts, preprocess, hpc

receptor = artifacts.get("art_receptor")
if receptor.get("format") != "pdbqt":
    receptor = preprocess.prepare_receptor(artifact_id=receptor["artifact_id"])

ligands = [artifacts.get(artifact_id) for artifact_id in ["lig_1", "lig_2", "lig_3"]]
results = []

for ligand in ligands:
    if ligand.get("format") != "pdbqt":
        ligand = preprocess.prepare_ligand(artifact_id=ligand["artifact_id"])

    result = hpc.vina(
        receptor_artifact_id=receptor["artifact_id"],
        ligand_artifact_id=ligand["artifact_id"],
        params={
            "center": (0, 0, 0),
            "size": (10, 10, 10),
        },
    )
    results.append(result)

for result in results:
    for item in result.get("artifacts", []):
        print(item["artifact_id"])
```

Rules:

- Dry-run must show total job count before execution.
- Quota must limit CPU, memory, wall time, job count, and output size.
- Approval should cover the planned batch, not an unbounded loop.
- Avoid dynamic discovery of unlimited work inside the sandbox.
