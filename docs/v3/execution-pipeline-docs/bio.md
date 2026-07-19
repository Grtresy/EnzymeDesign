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

`bio.hmmer_search` keeps route policy `bio.hmmer_search.provider:v1` and uses
`provider_config:ebi_hmmer:v2`. The configured result `page_size` defaults to
and is capped at `1000`. Poll requests explicitly carry
`page=1&page_size=<configured>`; a terminal poll payload is consumed only for
job status and `result.stats.nreported`, never as result page 1 even when the
provider includes hits in that body. Result materialization always starts with
an explicit `page=1` request at the same page size and then requests every page
through the stable declared `page_count`. Every result page must report the
same non-negative page count. For a non-truncated result, the materialized raw
hit count must equal terminal `nreported`; a successful empty result is valid
only as `nreported=0`, provider `page_count=0`, and `hits=[]` on the explicit
first result request. `max_hits`, provider ordering, and the parsed-hit schema
are unchanged.

`bio.uniprot_fetch` keeps route policy `bio.uniprot_fetch.provider:v1` and uses
`provider_config:uniprot:v3` with identity contract
`uniprot_primary_sequence_identity@2`. One SDK call remains one
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
`query_batch_size_cap=100`, and `estimated_query_batch_count`; the corrected
complete `37772`
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

The UniProt identity result is an exact mutually exclusive partition of the
requested set. Active records retain the strict sequence/audit/version contract.
An inactive member is accepted only when the producing query returns the exact
requested primary accession with `entryType=Inactive` and a supported
`inactiveReasonType`. The typed discriminated union accepts `DELETED` only with
a non-empty canonical deletion reason and accepts `MERGED` only with non-empty,
unique `mergeDemergeTo` replacement-target annotations. Both variants retain a
valid UniParc id, release/retrieval identity and response/record digests; both
have no sequence or entry audit, are excluded before the length filter, and are
never followed, fetched, or supplied sequence bytes from a replacement,
UniParc, or HMMER. The downstream join identity mapping fixes
`identity_replaced=false` for either variant; each MERGED target annotation
also fixes `identity_replaced=false` and `target_followed=false`. Unknown,
`DEMERGED`, or malformed
inactive records, active records without sequence, duplicate/extra identities,
a missing requested member, or a completely empty provider response fail
closed. An all-inactive but otherwise complete set emits the typed exact-zero
`sequences.fasta` under `fasta_zero_records@1` rather than a sentinel.

The `@2` provider metadata carries a non-empty ordered `response_digests` list;
`aggregate_response_digest` is the SHA-256 of its canonical JSON
serialization, and every active/inactive `response_digest` must be a member of
that ordered page set. An inactive `record_digest` is likewise recomputed from
the exact canonical `provider_metadata` object. The metadata is also closed
over the partition counters
`active_record_count`, `inactive_record_count`,
`inactive_deleted_record_count`, and `inactive_merged_record_count`. Every
`inactive_records[]` member has exactly
`requested_accession`, `primary_accession`, `uniprot_identifier`,
`entry_type`, `inactive_reason`, `uniparc_id`, `uniprot_release`,
`uniprot_release_date`, `retrieved_at`, `response_digest`,
`record_digest`, and `provider_metadata`. The `inactive_reason` object is a
closed discriminator: DELETED is exactly
`{inactive_reason_type, deleted_reason}`; MERGED is exactly
`{inactive_reason_type, replacement_target_annotations}`. Each replacement
annotation is exactly `annotation_type=provider_inactive_replacement`,
`source_database=uniprotkb`, `source_accession=<requested accession>`,
`target_database=uniprotkb`, `target_accession=<provider target>`,
`relationship=merged_into`, `identity_replaced=false`, and
`target_followed=false`. Unknown or extra fields fail the closed schema rather
than being interpreted heuristically.

If a UniProt HTTP request fails, safe diagnostics add only query-batch
index/count/start/count/digest and bounded completed/requested page progress.
They never expose the raw request URL, accession values/list, or cursor.

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

When a sandbox provider operation has established its request draft and then
raises `PipelineSdkFailure`, the Host registers exactly the diagnostic
`provider_request.json`, `provider_observation.json`, and `provider_error.json`
through the same sandbox artifact boundary before rethrowing the original
canonical code/stage/retryability with safe artifact refs. This persistence is
not provider success, does not add an AOX normalized deliverable, and authorizes
neither retry nor operation replay.

Structured errors include `error_code`, `stage`, `retryable`, `hint`, and `details`. Timeout, quota, invalid accession, partial result, empty result, pagination failure, and schema drift must not be treated as ordinary empty success.
