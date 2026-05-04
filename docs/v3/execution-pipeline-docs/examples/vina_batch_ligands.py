from openzyme_pipeline import artifacts, preprocess, hpc

receptor = artifacts.get("art_receptor")
if receptor.get("format") != "pdbqt":
    receptor = preprocess.prepare_receptor(artifact_id=receptor["artifact_id"])

ligand_ids = ["art_ligand_1", "art_ligand_2", "art_ligand_3"]
results = []

for ligand_id in ligand_ids:
    ligand = artifacts.get(ligand_id)
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
