# Bio Database SDK

Use `openzyme_pipeline.bio` for external biological database work. Sandbox code must not import `requests`, `httpx`, `urllib`, `Bio.Entrez`, or use provider credentials directly.

```python
from openzyme_pipeline import artifacts, bio

ncbi = bio.ncbi_fetch_proteins(
    accessions=["P12345"],
    output_dir="/workspace/output/bio/ncbi",
)
uniprot = bio.uniprot_fetch(
    accessions=["Q8XYZ1"],
    output_dir="/workspace/output/bio/uniprot",
    fields=["length", "taxonomy"],
    batch_size=50,
)
hmmer = bio.hmmer_search(
    hmm_artifact_id="art_hmm",
    hmm_artifact_digest="sha256:<64-lowercase-hex>",
    database="refprot",
    output_dir="/workspace/output/bio/hmmer",
    params={"E": 1e-5},
)
ncbi_fasta = artifacts.provider_file_ref(
    ncbi,
    relative_path_suffix="/provider_parsed/proteins.fasta",
)
```

Functions:

- `bio.ncbi_fetch_proteins(accessions=[...], output_dir="/workspace/output/...", fields=[...])`
- `bio.uniprot_fetch(accessions=[...], output_dir="/workspace/output/...", fields=[...], batch_size=...)`
- `bio.hmmer_search(hmm_artifact_id=..., hmm_artifact_digest=..., database="refprot", output_dir="/workspace/output/...", params=...)`

The Host performs provider requests, pagination, quota checks, parsing, and artifact registration. RPC results are bounded summaries: artifact ids, counts, provider/database metadata, digest summaries, transcript manifests, and warnings. `output_dir` must be under `/workspace/output/...`; provider_request, provider_observation, sanitized raw pages, parsed FASTA/metadata, raw HMMER hits JSON, and parsed hits CSV are written there and registered through the artifact boundary. In supervised sandbox mode, `bio.hmmer_search` requires the exact sealed `hmm_artifact_id` plus its `sha256:<64 lowercase hex>` digest; an HPC-produced HMM exposes that pair as `fetch_refs[].registered_artifact_id` and `fetch_refs[].output_digest` after `ws.fetch_outputs(run)`.

Use `artifacts.provider_file_ref(...)` for parsed provider files. It inspects
only the canonical `result_summary.transcript_manifest.files` list and requires
one exact `relative_path` suffix plus a canonical artifact id/digest. Never
recursively scan the full operation response: the same file may appear again
inside nested provenance, and treating that explanatory copy as another file
can cause an already-completed provider call to be replayed. A local selection
error is non-retryable and does not authorize a second controlled operation.

Structured errors include `error_code`, `stage`, `retryable`, `hint`, and `details`. Timeout, quota, invalid accession, partial result, empty result, pagination failure, and schema drift must not be treated as ordinary empty success.
