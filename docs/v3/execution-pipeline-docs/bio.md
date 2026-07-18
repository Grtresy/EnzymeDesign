# Bio Database SDK

Use `openzyme_pipeline.bio` for external biological database work. Sandbox code must not import `requests`, `httpx`, `urllib`, `Bio.Entrez`, or use provider credentials directly.

```python
from openzyme_pipeline import bio

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
```

Functions:

- `bio.ncbi_fetch_proteins(accessions=[...], output_dir="/workspace/output/...", fields=[...])`
- `bio.uniprot_fetch(accessions=[...], output_dir="/workspace/output/...", fields=[...], batch_size=...)`
- `bio.hmmer_search(hmm_artifact_id=..., hmm_artifact_digest=..., database="refprot", output_dir="/workspace/output/...", params=...)`

The Host performs provider requests, pagination, quota checks, parsing, and artifact registration. RPC results are bounded summaries: artifact ids, counts, provider/database metadata, digest summaries, transcript manifests, and warnings. `output_dir` must be under `/workspace/output/...`; provider_request, provider_observation, sanitized raw pages, parsed FASTA/metadata, raw HMMER hits JSON, and parsed hits CSV are written there and registered through the artifact boundary. In supervised sandbox mode, `bio.hmmer_search` requires the exact sealed `hmm_artifact_id` plus its `sha256:<64 lowercase hex>` digest; an HPC-produced HMM exposes that pair as `fetch_refs[].registered_artifact_id` and `fetch_refs[].output_digest` after `ws.fetch_outputs(run)`.

Structured errors include `error_code`, `stage`, `retryable`, `hint`, and `details`. Timeout, quota, invalid accession, partial result, empty result, pagination failure, and schema drift must not be treated as ordinary empty success.
