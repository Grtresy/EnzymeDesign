# SDK Overview

Execution pipelines are Python programs that run inside the V3 execution sandbox.

Allowed import:

```python
from openzyme_pipeline import artifacts, bio, bio_tools, preprocess, hpc
```

Core modules:

- `artifacts`: read authorized inputs and register output artifacts.
- `bio`: request Host-supervised NCBI, UniProt, and EBI HMMER database operations.
- `bio_tools`: request Host-supervised MAFFT, CD-HIT, and HMMER CLI operations.
- `preprocess`: prepare local molecular inputs inside the sandbox.
- `hpc`: request supervised HPC jobs through the Host supervisor.

The pipeline cannot directly use SSH, Slurm, runner config, database connections, arbitrary network clients, shell/subprocess, local bioinformatics binaries, or arbitrary host paths. Network database work must go through `bio.*`; sequence-mining CLI work must go through `bio_tools.*`; HPC work must go through `hpc.*` SDK calls.

`hpc.*` calls are supervised operations. The Host supervisor applies SDK operation policy, quota, and approval gates. The default path is dry-run first: `execution.pipeline.start` builds an `ExecutionPlan`, Web UI approves the plan, then the sandbox executes. Runtime SDK calls can still trigger a secondary approval gate if the sandbox requests an unapproved or changed HPC operation. Pipeline code should not implement its own approval or resume protocol.

Typical flow:

```python
from openzyme_pipeline import artifacts, hpc

structure = artifacts.get("art_structure")
result = hpc.fpocket(structure_artifact_id=structure["artifact_id"])

for item in result.get("artifacts", []):
    print(item["artifact_id"])
```

Before execution, the system runs a dry-run / validation pass. Fix dry-run errors before submitting the pipeline; dry-run output may also describe which SDK operations are expected to require approval.
