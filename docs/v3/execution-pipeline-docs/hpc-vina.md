# HPC Vina

Use `hpc.vina` for AutoDock Vina docking.

Required inputs:

- `receptor_artifact_id`: PDBQT artifact id
- `ligand_artifact_id`: PDBQT artifact id

Common parameters:

- `center`: `(x, y, z)` docking box center
- `size`: `(x, y, z)` docking box size
- `exhaustiveness`: integer, default depends on tool contract
- `num_modes`: integer, default depends on tool contract

Example:

```python
from openzyme_pipeline import artifacts, preprocess, hpc

receptor = artifacts.get("art_receptor")
ligand = artifacts.get("art_ligand")

if receptor.get("format") != "pdbqt":
    receptor = preprocess.prepare_receptor(artifact_id=receptor["artifact_id"])

if ligand.get("format") != "pdbqt":
    ligand = preprocess.prepare_ligand(artifact_id=ligand["artifact_id"])

result = hpc.vina(
    receptor_artifact_id=receptor["artifact_id"],
    ligand_artifact_id=ligand["artifact_id"],
    params={
        "center": (0, 0, 0),
        "size": (10, 10, 10),
        "exhaustiveness": 8,
        "num_modes": 9,
    },
)

for item in result.get("artifacts", []):
    print(item["artifact_id"])
```

Expected outputs:

- `vina_out.pdbqt`
- `vina.log`

Dry-run checks:

- receptor and ligand are PDBQT
- artifact ids are authorized
- docking box parameters are numeric
- expected outputs are declared
- job count and resources are within quota
- Host supervisor policy determines whether the docking job or batch requires approval; the default path is dry-run plan approval before sandbox execution, with runtime approval only as a secondary gate
