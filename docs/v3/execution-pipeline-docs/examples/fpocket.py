from openzyme_pipeline import artifacts, hpc

structure = artifacts.get("art_structure")
result = hpc.fpocket(structure_artifact_id=structure["artifact_id"])

for item in result.get("artifacts", []):
    print(item["artifact_id"])
