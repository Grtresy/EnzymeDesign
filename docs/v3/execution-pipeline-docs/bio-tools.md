# Bio Tools SDK

Use `openzyme_pipeline.bio_tools` for AOX/HMM sequence-mining tools. Pipeline code must not call `subprocess`, shell, MAFFT, CD-HIT, HMMER binaries, SSH, Slurm, or runner config directly.

```python
from openzyme_pipeline import artifacts, bio, bio_tools, hpc

ws = hpc.workspace("aox_hmm")
sequences = ws.stage_artifact("art_sequences", workspace_path="input/sequences.fasta")

clustered_run = bio_tools.cdhit(
    input_fasta=sequences,
    placement=ws,
    expected_outputs=[
        {
            "path": "bio_tools/cdhit/clustered.fasta",
            "kind": "sequence",
            "format": "fasta",
        },
        {
            "path": "bio_tools/cdhit/clusters.csv",
            "kind": "result",
            "format": "csv",
        },
    ],
    identity=0.9,
    mode="protein",
)
clustered_outputs = ws.fetch_outputs(clustered_run)
clustered_fasta_ref = artifacts.fetched_output_ref(
    clustered_outputs,
    declared_output_path="bio_tools/cdhit/clustered.fasta",
)
clustered_fasta = clustered_fasta_ref["artifact_id"]

alignment_run = bio_tools.mafft(
    input_fasta=ws.stage_artifact(
        clustered_fasta, workspace_path="input/clustered.fasta"
    ),
    placement=ws,
    expected_outputs=[
        {
            "path": "bio_tools/mafft/alignment.fasta",
            "kind": "sequence",
            "format": "fasta",
        }
    ],
)
alignment_outputs = ws.fetch_outputs(alignment_run)
alignment_fasta_ref = artifacts.fetched_output_ref(
    alignment_outputs,
    declared_output_path="bio_tools/mafft/alignment.fasta",
)
alignment_fasta = alignment_fasta_ref["artifact_id"]

hmm_run = bio_tools.hmmbuild(
    alignment=ws.stage_artifact(
        alignment_fasta, workspace_path="input/alignment.fasta"
    ),
    placement=ws,
    expected_outputs=[
        {
            "path": "bio_tools/hmmbuild/model.hmm",
            "kind": "result",
            "format": "hmm",
        }
    ],
)
hmm_outputs = ws.fetch_outputs(hmm_run)
hmm_artifact_ref = artifacts.fetched_output_ref(
    hmm_outputs,
    declared_output_path="bio_tools/hmmbuild/model.hmm",
)
hmm_artifact = hmm_artifact_ref["artifact_id"]

hmmalign_run = bio_tools.hmmalign(
    hmm=ws.stage_artifact(hmm_artifact, workspace_path="input/model.hmm"),
    fasta=sequences,
    placement=ws,
    expected_outputs=[
        {
            "path": "bio_tools/hmmalign/aligned.fasta",
            "kind": "sequence",
            "format": "fasta",
        }
    ],
)
hmmalign_outputs = ws.fetch_outputs(hmmalign_run)
aligned_fasta_ref = artifacts.fetched_output_ref(
    hmmalign_outputs,
    declared_output_path="bio_tools/hmmalign/aligned.fasta",
)
hits = bio.hmmer_search(
    hmm_artifact_id=hmm_artifact,
    hmm_artifact_digest=hmm_artifact_ref["content_digest"],
    database="refprot",
    output_dir="/workspace/output/bio/hmmer",
)
```

In supervised sandbox mode, every HPC input passed to `bio_tools.*` must be the
exact `hpc_stage_ref` object returned by `ws.stage_artifact(...)`. Pass that
return value directly, as the examples above do. Do not hand-write or
reconstruct an artifact/digest/path dictionary: the SDK rejects malformed
ad-hoc descriptors before the Host RPC with
`PipelineSdkError(error_code="hpc_stage_ref_required")` and directs the caller
back to `ws.stage_artifact(...)`. The Host remains the authority for workspace
ownership, artifact authorization, and complete S11/S12 binding validation.

Functions:

- `bio_tools.cdhit(input_fasta=..., placement=..., expected_outputs=..., identity=..., mode=...)`
- `bio_tools.mafft(input_fasta=..., placement=..., expected_outputs=..., params=...)`
- `bio_tools.hmmbuild(alignment=..., placement=..., expected_outputs=..., params=...)`
- `bio_tools.hmmalign(hmm=..., fasta=..., placement=..., expected_outputs=..., params=...)`
- `bio_tools.hmmer_search_cli(hmm=..., target_fasta=..., placement=..., expected_outputs=..., params=...)`: public SDK name reserved for an offline/HPC route, but Session 14 keeps it disabled as `unsupported_in_s14`. Use `bio.hmmer_search(hmm_artifact_id=..., hmm_artifact_digest=..., database="refprot", output_dir="/workspace/output/...")` for the current AOX/HMM main route.

`bio_tools.cdhit` 的 canonical membership 输出固定为
`cdhit_cluster_membership@1`，每个真实 `.clstr` member 一行，列顺序为
`cluster_id,member_id,representative_id,is_representative,identity_to_representative,member_length`。
`identity_to_representative` 使用 `0..1` 的六位小数，且每簇必须恰有一个
identity 为 `1.000000` 的 representative。Host 在登记任何 CD-HIT output 前，必须把
membership 的成员全集和长度与 staged FASTA 逐项核对；legacy aggregate schema、缺失或重复
member、代表不一致、长度漂移或 malformed `.clstr` 均 fail closed。runner smoke 和
`DeterministicBioToolsAdapter` 只产生 `fixture_non_cutover` 证据，不能满足科学 cutover。

The Host supervisor owns tool discovery, preflight, static route policy, resource estimates, expected outputs, output format validation, log truncation, and artifact registration. Pipeline RPC for enabled `bio_tools.*` operations returns a run handle; output artifact refs are produced by `ws.fetch_outputs(run)`. Full outputs and oversized logs must be stored as artifacts.

The four enabled runner templates own the exact output paths shown above. Declare the complete path set, call `ws.fetch_outputs(run)` even for a terminal tool operation, and select an output through the unique `fetch_refs[].declared_output_path` match. Do not depend on `registered_artifact_ids` or `artifacts` list order. A fetched ref's `registered_artifact_id` and `output_digest` form the exact input pair required when a provider operation consumes that artifact. Provider operations return a full controlled-operation response; select parsed provider files from `result_summary.transcript_manifest.files` by their unique `relative_path` suffix, such as `/provider_parsed/proteins.fasta` or `/provider_parsed/sequences.fasta`.

Use `artifacts.fetched_output_ref(...)` to enforce that direct top-level
`fetch_refs` selection and normalize the result to `artifact_id` plus
`content_digest`. Do not recursively search `artifacts`, `resolved_artifacts`,
or nested provenance rows, which may describe the same fetched output again.
Use `artifacts.provider_file_ref(...)` for the provider counterpart. Both
helpers fail closed on direct ambiguity and never replay a completed operation.

Structured failures include `unsupported_in_s14`, `bio_tool_output_contract_mismatch`, `tool_missing`, `invalid_fasta`, `invalid_hmm`, `resource_limit_exceeded`, `declared_output_missing`, `invalid_csv`, `hpc_runner_timeout`, `hpc_runner_unavailable`, and true tool `nonzero_exit` failures. Runner-issued SSH connection failures remain transport failures with `retryable=true`; this does not authorize automatic resubmission or substitution of another backend. Do not substitute another tool or treat malformed declared output as success.
