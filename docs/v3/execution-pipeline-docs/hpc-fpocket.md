# fpocket With HPC Placement

Use `structure_tools.fpocket` for pocket detection on a protein structure. Use `hpc.workspace(...)`, `stage_artifact(...)`, and `fetch_outputs(...)` when the selected route runs on HPC.

The stable boundary is Host-supervised execution: no SSH, Slurm, runner path, SIF path, database mount, or Host artifact path in pipeline code.

Required input:

- `structure`: staged PDB artifact ref
- The source artifact must either have a `.pdb` storage/relative path or metadata `format=pdb`.
- The artifact must contain at least 50 `ATOM`/`HETATM` records and at least 10 residues. Tiny toy PDB snippets are rejected as `invalid_fpocket_input`.

Example:

```python
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
```

Expected output:

- `target_out` directory
- After approval, the executor should inspect sandbox/execution status or workspace artifacts and write a `delegation_result` with the fpocket summary, including pocket count when available and output artifact ids.
- The master agent, not the executor, reports that result in chat after reading restore context and/or `protocol.thread(correlation_id)`.
- The chat result should not be `Execution finished: Pipeline sandbox completed.`; that text only describes the sandbox wrapper.

Dry-run checks:

- structure artifact is authorized
- structure format is PDB
- structure has enough atom and residue records for fpocket
- expected output directory is declared
- job resources are within quota
- Host supervisor policy determines whether this HPC job requires approval; the default path is operation-preview approval before remote execution, with runtime approval only as a secondary gate

Invalid fpocket inputs fail before approval and are not submitted to HPC. Approved execution failures return to the executor with structured `pipeline.error`; only when the executor determines the failure is not correctable should it mark the canonical execution task with `status=failed`, `failure_summary`, and `failure_ref`. Protocol messages are diagnostic context, not the task terminal state.
