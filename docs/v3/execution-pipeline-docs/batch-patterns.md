# Batch Patterns

Batch pipelines are allowed when they stay within approval and quota limits.

Batch examples use explicit `hpc` placement plus domain operations such as `docking.vina`. The Host supervisor must see the full planned operation set, backend route, quota estimate, expected outputs, and approval requirements before execution.

Use a simple loop and let each supervised backend call create a separate run:

```python
from openzyme_pipeline import artifacts, preprocess, hpc, docking

receptor = artifacts.get("art_receptor")
if receptor.get("format") != "pdbqt":
    receptor = preprocess.prepare_receptor(artifact_id=receptor["artifact_id"])
else:
    artifacts.materialize(receptor["artifact_id"], target_path="/workspace/input/receptor.pdbqt")

ws = hpc.workspace("vina_batch")
remote_receptor = ws.stage_artifact(
    receptor["artifact_id"],
    workspace_path="inputs/receptor.pdbqt",
)

ligand_ids = ["lig_1", "lig_2", "lig_3"]
results = []

for ligand_id in ligand_ids:
    ligand = artifacts.get(ligand_id)
    if ligand.get("format") != "pdbqt":
        ligand = preprocess.prepare_ligand(artifact_id=ligand["artifact_id"])
    else:
        artifacts.materialize(ligand["artifact_id"], target_path=f"/workspace/input/{ligand_id}.pdbqt")

    remote_ligand = ws.stage_artifact(
        ligand["artifact_id"],
        workspace_path=f"inputs/{ligand_id}.pdbqt",
    )
    run = docking.vina(
        receptor=remote_receptor,
        ligand=remote_ligand,
        placement=ws,
        params={
            "center": (0, 0, 0),
            "size": (10, 10, 10),
        },
        expected_outputs=[
            {"path": f"outputs/{ligand_id}/vina_out.pdbqt", "kind": "structure", "format": "pdbqt"},
            {"path": f"outputs/{ligand_id}/vina.log", "kind": "log", "format": "txt"},
        ],
    )
    results.append(ws.fetch_outputs(run))

for result in results:
    for item in result.get("artifacts", []):
        print(item["artifact_id"])
```

Rules:

- Dry-run must show total job count before execution.
- Quota must limit CPU, memory, wall time, job count, and output size.
- Approval should cover the planned batch, not an unbounded loop.
- Avoid dynamic discovery of unlimited work inside the sandbox.
