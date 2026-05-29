# SDK Overview

Execution pipelines are Python programs and supporting files authored inside the executor persistent sandbox.

The sandbox is the executor's working copy. It can contain scripts, pipeline modules, temporary notes, intermediate files, and logs. Canonical OpenZyme state is created only when the executor explicitly materializes input artifacts, registers output artifacts, snapshots code, or runs supervised SDK operations that the Host records as plans, runs, approvals, and provenance.

Allowed import:

```python
from openzyme_pipeline import artifacts, bio, bio_tools, preprocess, hpc, structure_tools, docking
```

`hpc` is the placement / remote workspace / declarative stage-fetch namespace. Domain operations are expressed through `bio`, `bio_tools`, `structure_tools`, and `docking`.

Core modules:

- `artifacts`: materialize authorized inputs, register output artifacts, and snapshot source code.
- `bio`: request Host-supervised NCBI, UniProt, and EBI HMMER database operations.
- `bio_tools`: request Host-supervised MAFFT, CD-HIT, and HMMER CLI operations.
- `preprocess`: prepare local molecular inputs inside the sandbox.
- `structure_tools`: request Host-supervised structure analysis operations such as fpocket.
- `docking`: request Host-supervised docking operations such as Vina.
- `hpc`: create logical placement workspaces and declare stage/fetch file flow for remote execution.

The sandbox file/command tools may run ordinary bash and Python within the isolated container. Pipeline code cannot directly use SSH, Slurm, runner config, database connections, arbitrary network clients, Host paths, local bioinformatics binaries outside the sandbox contract, or runner credentials. Network database work must go through `bio.*`; sequence-mining CLI work must go through `bio_tools.*`; structure and docking work must go through domain modules and explicit `hpc` placement when the selected route is remote/HPC.

External SDK calls are supervised operations. The Host supervisor applies SDK operation policy, quota, and approval gates. The stable executor-facing path is sandbox-first: edit files in the persistent sandbox workspace, snapshot source when needed, and run code through `sandbox.exec`; the Host builds an `ExecutionPlan`, asks the Web UI for approval when needed, then continues the supervised operation. Current migration code may still mention `execution.pipeline.start`, but that is a compatibility bridge rather than the executor authoring contract. AOX/HMM evals use a single-plan approval policy to require one plan approval across bio, bio_tools, external tool, and output-registration steps. Runtime SDK calls can still trigger a secondary approval gate if the sandbox requests an unapproved or changed operation. Pipeline code should not implement its own approval or resume protocol.

When registering derived outputs, pass `format` and `metadata.required_columns` for key FASTA/HMM/CSV artifacts. The sandbox control server rejects empty files, invalid FASTA/HMM content, and CSV files missing required columns before they can enter the artifact catalog.

Before dry-run or execution, snapshot the source that should be bound to the plan:

```python
from openzyme_pipeline import artifacts

source = artifacts.snapshot_code(
    paths="/workspace/src",
    entrypoint="/workspace/src/main.py",
    metadata={"purpose": "fpocket screening"},
)
```

The resulting code artifact is an audit snapshot, not the mutable working copy. Plans, approvals, runs, and output provenance must bind to its digest.

Typical flow:

```python
from openzyme_pipeline import artifacts, hpc, structure_tools

artifacts.materialize("art_structure", target_path="/workspace/input/structure.pdb")
source = artifacts.snapshot_code(paths="/workspace/src", entrypoint="/workspace/src/main.py")
ws = hpc.workspace("fpocket")
remote_structure = ws.stage_artifact(
    "art_structure",
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

Before execution, the system runs a dry-run / validation pass. Fix dry-run errors in the sandbox working copy, snapshot source again when code changes, and resubmit. Dry-run output may also describe which SDK operations are expected to require approval.
