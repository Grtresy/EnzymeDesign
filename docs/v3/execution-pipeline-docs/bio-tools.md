# Bio Tools SDK

Use `openzyme_pipeline.bio_tools` for AOX/HMM sequence-mining tools. Pipeline code must not call `subprocess`, shell, MAFFT, CD-HIT, HMMER binaries, SSH, Slurm, or runner config directly.

```python
from openzyme_pipeline import bio_tools

clustered = bio_tools.cdhit(input_fasta_artifact_id="art_sequences", identity=0.9, mode="protein")
alignment = bio_tools.mafft(input_fasta_artifact_id=clustered["artifact_ids"][0])
hmm = bio_tools.hmmbuild(alignment_artifact_id=alignment["artifact_ids"][0])
aligned = bio_tools.hmmalign(hmm_artifact_id=hmm["artifact_ids"][0], fasta_artifact_id="art_sequences")
hits = bio_tools.hmmer_search_cli(hmm_artifact_id=hmm["artifact_ids"][0], target_fasta_artifact_id="art_targets")
```

Functions:

- `bio_tools.cdhit(input_fasta_artifact_id=..., identity=..., mode=...)`
- `bio_tools.mafft(input_fasta_artifact_id=..., params=...)`
- `bio_tools.hmmbuild(alignment_artifact_id=..., params=...)`
- `bio_tools.hmmalign(hmm_artifact_id=..., fasta_artifact_id=..., params=...)`
- `bio_tools.hmmer_search_cli(hmm_artifact_id=..., target_fasta_artifact_id=..., params=...)`

The Host supervisor owns tool discovery, preflight, local-vs-HPC routing, resource estimates, expected outputs, output format validation, log truncation, and artifact registration. Pipeline RPC returns bounded summaries, warning/error fields, and artifact refs; full outputs and oversized logs must be stored as artifacts.

Structured failures include `tool_missing`, `invalid_fasta`, `invalid_hmm`, `resource_limit_exceeded`, `declared_output_missing`, `invalid_csv`, and timeout/HPC runner failures. Do not substitute another tool or treat malformed declared output as success.
