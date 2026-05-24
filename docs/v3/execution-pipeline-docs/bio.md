# Bio Database SDK

Use `openzyme_pipeline.bio` for external biological database work. Sandbox code must not import `requests`, `httpx`, `urllib`, `Bio.Entrez`, or use provider credentials directly.

```python
from openzyme_pipeline import bio

ncbi = bio.ncbi_fetch_proteins(accessions=["P12345"])
uniprot = bio.uniprot_fetch(accessions=["Q8XYZ1"], fields=["length", "taxonomy"], batch_size=50)
hmmer = bio.hmmer_search(hmm_artifact_id="art_hmm", database="uniprotkb", params={"E": 1e-5})
```

Functions:

- `bio.ncbi_fetch_proteins(accessions=[...], fields=[...])`
- `bio.uniprot_fetch(accessions=[...], fields=[...], batch_size=...)`
- `bio.hmmer_search(hmm_artifact_id=..., database=..., params=...)`

The Host performs provider requests, pagination, quota checks, parsing, and artifact registration. RPC results are bounded summaries: artifact ids, counts, provider/database metadata, digest summaries, and warnings. FASTA, metadata JSON/CSV, raw HMMER hits JSON, and parsed hits CSV are materialized as session artifacts.

Structured errors include `error_code`, `stage`, `retryable`, `hint`, and `details`. Timeout, quota, invalid accession, partial result, empty result, pagination failure, and schema drift must not be treated as ordinary empty success.
