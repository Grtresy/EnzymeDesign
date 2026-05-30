# Bio Tools SDK

Use `openzyme_pipeline.bio_tools` for AOX/HMM sequence-mining tools. Pipeline code must not call `subprocess`, shell, MAFFT, CD-HIT, HMMER binaries, SSH, Slurm, or runner config directly.

```python
from openzyme_pipeline import bio, bio_tools, hpc

ws = hpc.workspace("aox_hmm")
sequences = ws.stage_artifact("art_sequences", workspace_path="input/sequences.fasta")

clustered = bio_tools.cdhit(
    input_fasta=sequences,
    placement=ws,
    expected_outputs=[{"path": "work/cdhit/sequences_nr.fasta", "kind": "sequence"}],
    identity=0.9,
    mode="protein",
)
clustered_outputs = ws.fetch_outputs(clustered)
clustered_fasta = clustered_outputs["registered_artifact_ids"][0]

alignment = bio_tools.mafft(
    input_fasta=ws.stage_artifact(clustered_fasta, workspace_path="work/cdhit/sequences_nr.fasta"),
    placement=ws,
    expected_outputs=[{"path": "work/mafft/alignment.fasta", "kind": "sequence"}],
)
alignment_outputs = ws.fetch_outputs(alignment)
alignment_fasta = alignment_outputs["registered_artifact_ids"][0]

hmm = bio_tools.hmmbuild(
    alignment=ws.stage_artifact(alignment_fasta, workspace_path="work/mafft/alignment.fasta"),
    placement=ws,
    expected_outputs=[{"path": "work/hmmbuild/profile.hmm", "kind": "result"}],
)
hmm_outputs = ws.fetch_outputs(hmm)
hmm_artifact = hmm_outputs["registered_artifact_ids"][0]

aligned = bio_tools.hmmalign(
    hmm=ws.stage_artifact(hmm_artifact, workspace_path="work/hmmbuild/profile.hmm"),
    fasta=sequences,
    placement=ws,
    expected_outputs=[{"path": "work/hmmalign/aligned.sto", "kind": "sequence"}],
)
hits = bio.hmmer_search(
    hmm_artifact_id=hmm_artifact,
    database="refprot",
    output_dir="/workspace/output/bio/hmmer",
)
```

Functions:

- `bio_tools.cdhit(input_fasta=..., placement=..., expected_outputs=..., identity=..., mode=...)`
- `bio_tools.mafft(input_fasta=..., placement=..., expected_outputs=..., params=...)`
- `bio_tools.hmmbuild(alignment=..., placement=..., expected_outputs=..., params=...)`
- `bio_tools.hmmalign(hmm=..., fasta=..., placement=..., expected_outputs=..., params=...)`
- `bio_tools.hmmer_search_cli(hmm=..., target_fasta=..., placement=..., expected_outputs=..., params=...)`: public SDK name reserved for an offline/HPC route, but Session 14 keeps it disabled as `unsupported_in_s14`. Use `bio.hmmer_search(..., database="refprot", output_dir="/workspace/output/...")` for the current AOX/HMM main route.

The Host supervisor owns tool discovery, preflight, static route policy, resource estimates, expected outputs, output format validation, log truncation, and artifact registration. Pipeline RPC for enabled `bio_tools.*` operations returns a run handle; output artifact refs are produced by `ws.fetch_outputs(run)`. Full outputs and oversized logs must be stored as artifacts.

Structured failures include `unsupported_in_s14`, `tool_missing`, `invalid_fasta`, `invalid_hmm`, `resource_limit_exceeded`, `declared_output_missing`, `invalid_csv`, and timeout/HPC runner failures. Do not substitute another tool or treat malformed declared output as success.
