from openzyme_pipeline import artifacts, preprocess, hpc, docking

receptor = artifacts.get("art_receptor")
ligand = artifacts.get("art_ligand")

if receptor.get("format") != "pdbqt":
    receptor = preprocess.prepare_receptor(artifact_id=receptor["artifact_id"])
else:
    artifacts.materialize(receptor["artifact_id"], target_path="/workspace/input/receptor.pdbqt")

if ligand.get("format") != "pdbqt":
    ligand = preprocess.prepare_ligand(artifact_id=ligand["artifact_id"])
else:
    artifacts.materialize(ligand["artifact_id"], target_path="/workspace/input/ligand.pdbqt")

ws = hpc.workspace("vina_single")
remote_receptor = ws.stage_artifact(
    receptor["artifact_id"],
    workspace_path="inputs/receptor.pdbqt",
)
remote_ligand = ws.stage_artifact(
    ligand["artifact_id"],
    workspace_path="inputs/ligand.pdbqt",
)

run = docking.vina(
    receptor=remote_receptor,
    ligand=remote_ligand,
    placement=ws,
    params={
        "center": (0, 0, 0),
        "size": (10, 10, 10),
        "exhaustiveness": 8,
        "num_modes": 9,
    },
    expected_outputs=[
        {"path": "outputs/vina_out.pdbqt", "kind": "structure", "format": "pdbqt"},
        {"path": "outputs/vina.log", "kind": "log", "format": "txt"},
    ],
)
result = ws.fetch_outputs(run)

for item in result.get("artifacts", []):
    print(item["artifact_id"])
