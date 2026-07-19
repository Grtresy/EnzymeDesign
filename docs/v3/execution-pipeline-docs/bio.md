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

`bio.uniprot_fetch` uses `provider_config:uniprot:v2`. One SDK call remains one
approved controlled operation and may contain at most `100000` accessions. The
Host partitions that normalized set into fixed query batches of at most `100`
accessions; it does not create one operation or approval per query. The public
`batch_size` argument still sets the UniProt response-page `size` (maximum
`100`) and does not set the accession count of a query. Each query follows its
own `Link: rel=next` chain and has an independent `100`-page cap. A next link
remaining at that cap fails non-retryably as `provider_partial_result`.
Every next link must remain on
`https://rest.uniprot.org[:443]/uniprotkb/search`, with no userinfo or fragment.
A malformed or off-origin link fails as `provider_schema_drift`; diagnostics
retain only its SHA-256 digest and the fixed expected endpoint, never the
candidate URL.

Before approval the SDK resource estimate exposes `accession_count`,
`query_batch_size_cap=100`, and `estimated_query_batch_count`; `37722`
accessions therefore declare `378` provider queries inside the one controlled
operation. The sanitized transcript binds every request to global `page`,
`query_batch_index/query_batch_count`, accession start/count/digest, and
`page_in_query`, while the summary records total page count, page size,
per-query page cap, query count, and query cap. Duplicate accession detection
uses one frequency-map pass and deterministic sorting of only the duplicate
keys. Operation-cap and duplicate failures occur before HTTP.

Every response page is validated against the exact accession slice recorded for
the query that produced it. A record that maps to an accession requested by a
different query is a cross-query identity swap and fails non-retryably as
`provider_identity_mismatch`; membership in the operation-wide set is not
enough. The SDK's `100`-accession estimate is currently a transparent prediction
for the default provider config, not the authority that grants limits. Injected
Host `BioProviderHttpConfig` can tighten the actual query cap and performs the
final pre-HTTP validation. A canonical Host-computed estimate/limit snapshot
bound to approval is deferred in
[Host-authoritative controlled-operation resource estimate and limit snapshot](../architecture-proposals/host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md).

This contract deliberately does not switch to UniProt asynchronous ID Mapping.
The AOX input is already a set of primary UniProt accessions, so an identity
mapping job is not semantically required. Submit/poll/result handles,
idempotent recovery, durable continuation, approval and transcript/schema
migration would be a separate architecture change. The current bounded search
queries are not an async fallback and must not be replayed as separate
controlled operations.

Use `artifacts.provider_file_ref(...)` for parsed provider files. It inspects
only the canonical `result_summary.transcript_manifest.files` list and requires
one exact `relative_path` suffix plus a canonical artifact id/digest. Never
recursively scan the full operation response: the same file may appear again
inside nested provenance, and treating that explanatory copy as another file
can cause an already-completed provider call to be replayed. A local selection
error is non-retryable and does not authorize a second controlled operation.

Structured errors include `error_code`, `stage`, `retryable`, `hint`, and `details`. Timeout, quota, invalid accession, partial result, empty result, pagination failure, and schema drift must not be treated as ordinary empty success.
