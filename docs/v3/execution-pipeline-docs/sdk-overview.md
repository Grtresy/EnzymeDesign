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
- `aox_reference`, `aox_hmmer`, `aox_sequence_join`, `aox_motif`, and
  `aox_similarity`: versioned, deterministic AOX calculations with canonical
  result serializers. A workflow that pins these calculation identities must
  call the installed functions rather than reimplement or approximate them.

The sandbox file/command tools may run ordinary bash and Python within the isolated container. Pipeline code cannot directly use SSH, Slurm, runner config, database connections, arbitrary network clients, Host paths, local bioinformatics binaries outside the sandbox contract, or runner credentials. Network database work must go through `bio.*`; sequence-mining CLI work must go through `bio_tools.*`; structure and docking work must go through domain modules and explicit `hpc` placement when the selected route is remote/HPC.

External SDK calls are supervised operations. The Host supervisor applies SDK operation policy, quota, and approval gates. The stable executor-facing path is sandbox-first: edit files in the persistent sandbox workspace, snapshot source when needed, and run code through `sandbox.exec`; the Host builds an `ExecutionPlan`, asks the Web UI for approval when needed, then continues the supervised operation. Current migration code may still mention `execution.pipeline.start`, but that is a compatibility bridge rather than the executor authoring contract. AOX/HMM evals use a single-plan approval policy to require one plan approval across bio, bio_tools, external tool, and output-registration steps. Plans carry a static per-operation `max_calls`; repeated calls and literal bounded loops count toward it, while dynamically unbounded external calls fail before execution. The Host atomically consumes this budget before each provider/tool/HPC action. Runtime SDK calls can still trigger a secondary approval gate if the sandbox requests an unapproved or changed operation, but an exhausted approved call budget fails with `execution_plan_quota_exceeded` rather than reopening approval. Pipeline code should not implement its own approval or resume protocol.

The sandbox control transport is bounded newline-delimited JSON-RPC 2.0. One
Unix-socket connection carries exactly one request frame and one response frame;
each payload is limited to `4 MiB`, excluding its terminating newline. A
`64 KiB` socket read is only a chunk, not the message limit: both Host and SDK
assemble chunks through the newline. Invalid UTF-8/JSON, EOF before the
delimiter, response identity drift, and oversized frames fail closed with a
structured SDK/transport error. If non-whitespace bytes after the first newline
are already observed by the receiver, the request is rejected before dispatch.
The hard invariant is at most one executed request per connection: a second
frame arriving only after the first was accepted may observe connection close
instead of a second error response, but can never execute another method.
The SDK rejects an oversized request before sending it and bounds response
assembly symmetrically; the Host isolates malformed/disconnected clients so one
connection cannot terminate the control worker, and replaces an oversized
response with a small structured error. These failures never authorize an
operation replay or backend fallback. This correction retains the existing
sandbox protocol and image version; normal SDK source/commit digests still
change with the implementation.

A non-null JSON-RPC request `id` is either a string whose UTF-8 encoding is at
most `256` bytes or a signed 64-bit integer; booleans are not integer ids. If a
safe id was decoded but another request semantic is invalid, the structured
error preserves that id. If the id itself is oversized/invalid or cannot be
safely decoded, the error uses `id: null`. The client still requires exact
response identity and rejects drift.

For UniProt, `provider_config:uniprot:v2` keeps the whole accession set inside
one SDK call, one controlled operation, and one approval. The operation cap is
`100000` accessions; the Host creates fixed queries of at most `100` accessions
and applies the `Link` page cap independently to each query. `batch_size`
remains response page size, not query width. Approval resource projection must
show the estimated query count before provider I/O (`37722` accessions means
`378` queries under the default cap), and the transcript must preserve
query/page coordinates. Each response page is validated against the exact
accession slice that produced its query; a requested identity returned under a
different query is a cross-query swap and fails closed. The SDK estimate is a
transparent default-config prediction, not authorization or an authoritative
actual-limit snapshot: injected Host provider config may tighten the query cap
and performs final pre-I/O validation. The Host-authoritative estimate/limit
snapshot is a deferred architecture proposal. This bounded synchronous topology
does not introduce UniProt async ID-mapping jobs or authorize per-query
operation replay.

The S12 sandbox request envelope is plan-only. `adapter_result` and
`result_summary` are not SDK inputs and are rejected if sandbox code puts them
on the wire. Result envelopes, including toolchain runtime identity, may be
created only from an explicitly successful, error-free Host adapter executor
response whose result summary does not contradict that success, or from a validated,
approved completed result carrying both the public
`result_origin=host_adapter_executor` projection and its separate Host-owned
repository provenance column, then reused by the Host for the same operation
digest. Current-schema rows without that Host-owned column fail with
`adapter_result_origin_untrusted` for the same idempotency key and are never
silently executed again. A fresh key creates a fresh operation and approval,
even if formerly caller-controlled JSON contains the same marker string;
older SQLite schema versions retain the normal explicit schema-mismatch policy
and are not promised an automatic in-place migration.

Runner outputs are success-only scientific inputs. Non-success or unknown
runner status, missing toolchain identity, output validation failure, and
partial execution project an empty artifact set through runner, server,
adapter, and engine. Slurm fetch additionally requires an authoritative
`COMPLETED` state with exit code 0 before downloading any declared output.

The execution plan also binds the resolved immutable sandbox image id, the digest of the exact `openzyme_pipeline` SDK source tree mounted read-only into the container, and the sandbox protocol version. The Host revalidates this runtime identity immediately before execution and after SDK materialization, and Podman is launched by immutable image id rather than the configured tag. Persistent sandbox adapter operations inherit the identity recorded by their originating `SandboxRun`; identity drift or missing provenance is a fail-closed error before provider, tool, or runner activity.

When registering derived outputs, pass `format` and `metadata.required_columns`
for key FASTA/HMM/CSV artifacts. The sandbox control server rejects empty files,
invalid FASTA/HMM content, and CSV files missing required columns before they
can enter the artifact catalog. The explicit
`validation_profile="fasta_zero_records@1"` exception accepts only an exact
zero-byte sequence FASTA with a stable `empty_result_reason` and versioned
`derivation_contract_id`; it never accepts sentinel bytes and does not replace
workflow-specific scientific branch verification.

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
output = artifacts.fetched_output_ref(
    result,
    declared_output_path="target_out",
)
print(output["artifact_id"], output["content_digest"])
```

Before execution, the system runs a dry-run / validation pass. Fix dry-run errors in the sandbox working copy, snapshot source again when code changes, and resubmit. Dry-run output may also describe which SDK operations are expected to require approval.
