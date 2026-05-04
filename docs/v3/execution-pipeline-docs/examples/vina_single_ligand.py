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
