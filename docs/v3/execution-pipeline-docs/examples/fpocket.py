from openzyme_pipeline import artifacts, hpc, structure_tools

structure = artifacts.get("art_structure")
artifacts.materialize(structure["artifact_id"], target_path="/workspace/input/structure.pdb")
ws = hpc.workspace("fpocket")
remote_structure = ws.stage_artifact(
    structure["artifact_id"],
    workspace_path="inputs/structure.pdb",
)
run = structure_tools.fpocket(
    structure=remote_structure,
    placement=ws,
    expected_outputs=[
        {"path": "target_out", "kind": "directory", "format": "fpocket"},
    ],
)
result = ws.fetch_outputs(run)

for item in result.get("artifacts", []):
    print(item["artifact_id"])
