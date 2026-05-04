# Preprocess

Use `preprocess` when current artifacts do not match the downstream HPC tool input format.

Common functions:

- `preprocess.convert_format(artifact_id=..., output_format=...)`
- `preprocess.prepare_receptor(artifact_id=...)`
- `preprocess.prepare_ligand(artifact_id=...)`
- `preprocess.smiles_to_3d(smiles=..., title=...)`

Vina requires PDBQT receptor and ligand inputs. If receptor or ligand is not already PDBQT, prepare it first:

```python
from openzyme_pipeline import artifacts, preprocess

receptor = artifacts.get("art_receptor")
if receptor.get("format") != "pdbqt":
    receptor = preprocess.prepare_receptor(artifact_id=receptor["artifact_id"])

ligand = artifacts.get("art_ligand")
if ligand.get("format") != "pdbqt":
    ligand = preprocess.prepare_ligand(artifact_id=ligand["artifact_id"])
```

Preprocess outputs must become trusted session artifacts before an `hpc.*` step consumes them. The SDK should handle registration or return a registerable artifact reference; dry-run must show the created artifact ids.

Common dry-run error:

```text
hpc.vina requires ligand format pdbqt. Current artifact art_ligand format is sdf.
Call preprocess.prepare_ligand(artifact_id=ligand["artifact_id"]) first.
```
