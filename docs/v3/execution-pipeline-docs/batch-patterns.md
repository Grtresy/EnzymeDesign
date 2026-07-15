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

results = []

for ligand_id in ("lig_1", "lig_2", "lig_3"):
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

- Dry-run must show each supervised operation's static `max_calls` and the total job/request count before execution. Repeated direct calls and literal bounded loops count toward that bound.
- Quota must limit CPU, memory, wall time, job count, and output size.
- Approval covers the exact bounded batch. The Host atomically consumes the approved per-operation call budget before each provider/tool/HPC action and returns `execution_plan_quota_exceeded` before touching the adapter/runner when exhausted.
- External SDK calls inside dynamic iterables, functions, `while`, or comprehensions are rejected as `execution_plan_unbounded_calls`. Materialize a finite list first, then author the formal execution source with a literal tuple/list bound.
