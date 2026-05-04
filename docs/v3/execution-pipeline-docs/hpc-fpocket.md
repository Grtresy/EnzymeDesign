# HPC fpocket

Use `hpc.fpocket` for pocket detection on a protein structure.

Required input:

- `structure_artifact_id`: PDB artifact id
- The artifact must either have a `.pdb` storage/relative path or metadata `format=pdb`.
- The artifact must contain at least 50 `ATOM`/`HETATM` records and at least 10 residues. Tiny toy PDB snippets are rejected as `invalid_fpocket_input`.

Example:

```python
from openzyme_pipeline import artifacts, hpc

structure = artifacts.get("art_structure")
result = hpc.fpocket(structure_artifact_id=structure["artifact_id"])

for item in result.get("artifacts", []):
    print(item["artifact_id"])
```

Expected output:

- `target_out` directory
- After approval, the executor should call `execution.pipeline.status` or inspect workspace artifacts and write a `delegation_result` with the fpocket summary, including pocket count when available and output artifact ids.
- The master agent, not the executor, reports that result in chat after reading restore context and/or `protocol.thread(correlation_id)`.
- The chat result should not be `Execution finished: Pipeline sandbox completed.`; that text only describes the sandbox wrapper.

Dry-run checks:

- structure artifact is authorized
- structure format is PDB
- structure has enough atom and residue records for fpocket
- expected output directory is declared
- job resources are within quota
- Host supervisor policy determines whether this HPC job requires approval; the default path is dry-run plan approval before sandbox execution, with runtime approval only as a secondary gate

Invalid fpocket inputs fail before approval and are not submitted to HPC. Approved execution failures return to the executor with structured `pipeline.error`; only when the executor determines the failure is not correctable should it mark the canonical execution task with `status=failed`, `failure_summary`, and `failure_ref`. Protocol messages are diagnostic context, not the task terminal state.
