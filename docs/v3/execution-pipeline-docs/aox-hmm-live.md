# AOX/HMM Live Cutover Workflow Knowledge

This document is the domain SOP for the explicitly selected workflow reference
`workflow:aox-hmm-live@2.0.0#sha256:<manifest-digest>`. Version `2.0.0` is the
correctional breaking contract: it replaces legacy activity-score and fixture
semantics rather than silently accepting a `1.x` result. It is not a generic
harness prompt rule and must not be selected by matching words in a user
message, task subject, or delegation instructions.

The structured workflow manifest pins this document by `doc_id`, `version`, and
`content_sha256`. The harness must reject a missing document, version mismatch,
or digest mismatch before a model/provider call. `docs.search` and `docs.read`
return the current version and digest; callers may pass both values back to
`docs.read` for an exact fail-closed read.

## Fixed outcomes, free strategy

The pack fixes scientific inputs, provider/tool outcomes, calculation and
schema identities, evidence closure, and fail-closed acceptance. It does not
define a workflow graph. The master and teammates remain free to choose
queries, batching, bounded retries, intermediate inspections, legal operation
ordering, and report structure. They may also stop early when a real
prerequisite fails. They must not weaken or substitute the fixed outcomes to
make a path runnable.

The `2.0.0` manifest directly pins this document plus the motif and similarity
contract documents. The installed scientific identities required by this pack
are:

| contract | id | contract/calculation digest | implementation digest |
|---|---|---|---|
| motif rule | `aox_motif_rule_score@1` | `sha256:71aff3b872aaef3254550db53c7554011923d19293f9c5837ddc4bb8ca0bec10` | `sha256:795535d9d6c232a79bc9791f8c2780c2f4aa64b234b15a83deb8c76d3406871c` |
| real-sequence similarity | `aox_global_sequence_identity@1` | `sha256:12f98c34460aa3bc59b84c5553771b0bbfb25354febd6558ec381535a0e8286d` | `sha256:300ea35bff801782b6bde96d12f206881a6a5aac26a96708ae6756c800aab9b5` |
| HMM reference selection | `aox_hmm_reference_set_selection@1` | `sha256:34659d9f384af0b9d63f2d7d66f21927cd438ad222458169114835ec368ebbbf` | `sha256:8abb77c737fcf29ee659e0ae0ef7204ecc8f0f49843eb4a0098a4b5edc2666ba` |
| coordinate reference selection | `aox_reference_selection@1` | `sha256:1923a047f4bf0ce5b70f9c1bfa16a2e6453379abd1850d7bf7654a4721bb0f49` | `sha256:8abb77c737fcf29ee659e0ae0ef7204ecc8f0f49843eb4a0098a4b5edc2666ba` |
| scoring input assembly | `aox_scoring_input_assembly@1` | `sha256:42e9926ac2f9a8b88d3117838f919d8a966171a65265854dabb6105ef4255e85` | `sha256:8abb77c737fcf29ee659e0ae0ef7204ecc8f0f49843eb4a0098a4b5edc2666ba` |
| pre-UniProt HMMER score filter | `hmmer_score_filtered_accessions@1` | `sha256:3bc1d3d3fd297a11ba495d07ce097417b5193387197242fa6784d006937c6331` | `sha256:3f98642b4fa7409d8a8cea04d1cf24c2f8c935ad00248a464ca97af7d6136112` |
| UniProt sequence/length join | `aox_sequence_length_join@2` | `sha256:f6fe62bb4dcf1c859124bedb93337dae7dae0ebfeaa0c39a9b4736d05f57d41a` | `sha256:f17c08d61cd9c31ed45b0cc2d2a40e8d5b6d5b6e3bd493c24ea362c916065243` |

The graph closure binds `cdhit_cluster_membership@1`,
`aox_candidate_graph_nodes@1`, `aox_candidate_graph_edges@1`, and
`aox_candidate_similarity_graph_manifest@1`. Any installed identity or pinned
knowledge-document digest drift is a scientific prerequisite failure, not a
reason to infer the nearest version.

## Controlled execution boundary

Author Python source inside the executor's persistent sandbox workspace and run
it with `sandbox.exec`. Provider, tool, HPC, fetch, and artifact registration
work must go through the in-sandbox `openzyme_pipeline` SDK so the Host can
create approvals, `ControlledOperation` records, result envelopes, route-policy
evidence, provider/toolchain digests, backend run ids, and registered artifacts.

Do not call HTTP clients, `Bio.Entrez`, local MAFFT/CD-HIT/HMMER binaries, SSH,
Slurm, runner configuration, package installers, or Host paths. Do not replace
a failed or empty real operation with cached fixture sequences, the reference
accessions, pseudo-HMM construction, local stand-in clustering, invented scores,
synthetic hits, or fabricated graph edges.

Every `openzyme_pipeline.bio` provider call requires an explicit canonical
`output_dir="/workspace/output/<provider-specific-directory>"`. A relative
path, `/workspace/output` itself, `/workspace/input`, traversal, whitespace, or
a Host path is invalid. The SDK rejects these shapes before creating a
controlled operation; the Host repeats the authoritative validation after
approval. This is a path boundary, not a prescribed directory name: the agent
remains free to choose distinct meaningful subdirectories under the output
root. The minimum provider signatures are:

```python
bio.ncbi_fetch_proteins(
    accessions=[...],
    output_dir="/workspace/output/providers/ncbi_reference",
    fields=[...],
)
bio.hmmer_search(
    hmm_artifact_id=...,
    hmm_artifact_digest=...,
    database="refprot",
    output_dir="/workspace/output/providers/ebi_hmmer",
    params={...},
)
bio.uniprot_fetch(
    accessions=[...],
    output_dir="/workspace/output/providers/uniprot",
    source_hit_artifact={
        "artifact_id": ...,
        "content_digest": ...,
    },
)
```

The control transport accepts the legitimate large accession/metadata envelopes
this workflow can derive. It uses one JSON-RPC 2.0 NDJSON frame per Unix-socket
connection with a symmetric `4 MiB` request/response payload cap, excluding the
newline. The receiver assembles the frame across `64 KiB` socket chunks; a
single chunk is not the protocol limit. Invalid/incomplete frames, response
identity drift, and either direction exceeding `4 MiB` fail closed. If the Host
already observes non-whitespace bytes after the first newline, it rejects before
dispatch. At most one request may execute per connection; a second frame that
arrives only after the first was accepted may receive only connection close,
not a second error, but cannot become another controlled operation. A malformed client connection cannot terminate the Host
accept worker, and the SDK performs the matching request preflight and bounded
response read. Do not replay a completed HMMER operation or invent a smaller
accession set to work around a transport failure; preserve its attempt-local
checkpoint and fail the attempt if the canonical next request cannot satisfy
the bounded contract.

When present, the JSON-RPC request id is limited to a string of at most `256`
UTF-8 bytes or a signed 64-bit integer (not boolean). A semantic error elsewhere
in a decoded request preserves the safe id; an oversized/invalid id yields a
structured error with `id=null`. The SDK continues to require exact response-id
equality.

EBI HMMER keeps route policy `bio.hmmer_search.provider:v1` and binds
`provider_config:ebi_hmmer:v2`. Result `page_size` defaults to and is capped at
`1000`. Poll requests explicitly carry `page=1&page_size=<configured>`, but the
terminal payload is consumed only for status and `result.stats.nreported`; any
hits included there are never result page 1. Materialization starts with a
separate explicit page 1 at the same width and reads through one stable
cross-page `page_count`. For a non-truncated result, materialized raw hit count
must equal terminal `nreported`. A successful empty result is exactly
`nreported=0`, provider `page_count=0`, and `hits=[]` on the explicit first
result request. This does not change `max_hits`, provider order, score filtering,
or the 11-column parsed schema.

When the HMMER score filter is non-empty, the complete exact accession artifact
is passed once to `bio.uniprot_fetch` under `provider_config:uniprot:v3` and
`uniprot_primary_sequence_identity@2`. That
single SDK call is one controlled operation and one approval, with an operation
cap of `100000` accessions. The Host forms fixed queries of at most `100`
accessions; `batch_size` remains only the UniProt response page `size` (maximum
`100`), and `Link: rel=next` is followed with an independent `100`-page cap per
query. The pre-approval resource estimate exposes accession and query-batch
counts: the corrected complete current set of `37772` accessions therefore
requires `378` bounded queries inside
the one operation, not `378` operations or approvals. Query/page indices,
accession range/count/digest, response digests, total pages, and per-query cap
remain in the sanitized transcript. Duplicate detection is frequency based and
linear in the accession scan, with deterministic ordering of duplicate keys.

Pagination never grants a new network origin: every next link must be HTTPS
`rest.uniprot.org` (implicit or explicit port `443`), exact path
`/uniprotkb/search`, and contain no userinfo or fragment. A malformed or
off-origin link fails as `provider_schema_drift`; only its digest and the fixed
expected endpoint enter diagnostics.

Each response page is also bound to the exact query accession slice and digest
that produced it. A primary/secondary mapping to an accession from another
query is a cross-query identity swap and fails as `provider_identity_mismatch`,
even though that accession exists in the operation-wide request set. The SDK's
`378` count is transparent prediction under the default `100`-accession query
cap, not limit authority; the injected Host provider config may tighten the
actual cap and performs final pre-I/O validation. Making the Host compute and
seal the canonical resource/limit snapshot into approval is proposal-only in
[Host-authoritative controlled-operation resource estimate and limit snapshot](../architecture-proposals/host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md).

The provider result must be an exact active-plus-inactive partition of every
requested accession. An active raw record accepts only exact
`entryType="UniProtKB reviewed (Swiss-Prot)"` or
`entryType="UniProtKB unreviewed (TrEMBL)"`, deriving `reviewed=true` or
`reviewed=false` respectively. If raw `reviewed` is present it must be a boolean
equal to that discriminator; active `inactiveReason` is forbidden, and metadata
`entry_type`/`reviewed` must reproduce the same pair. Active records otherwise
retain strict sequence, entry-audit, release/version, retrieval and digest
fields. A typed inactive record
is accepted only for exact requested-primary identity in its producing query and
must form the `DELETED|MERGED` discriminated union. `DELETED` carries a
canonical non-empty deletion reason; `MERGED` carries non-empty unique
replacement-target annotations. Both variants carry UniParc id,
release/retrieval and response/record digests, have no sequence or entry audit,
are excluded before length filtering, are never followed/fetched/replaced, and
cannot borrow sequence from a replacement, UniParc, or HMMER. The downstream
join mapping fixes `identity_replaced=false` for either variant; each MERGED
annotation also fixes `identity_replaced=false` and `target_followed=false`.
`DEMERGED`, unknown/malformed inactive,
missing/duplicate/extra identity, active-without-sequence, or a completely empty
response fails closed. UniProt HTTP failures expose only safe batch
index/count/start/count/digest and bounded page progress, never the URL,
accession values/list, or cursor.

The corrected `37,772`-accession read-only provider census covered all
`378/378` query batches and observed `5,596` inactive identities:
`5,594 DELETED`, `2 MERGED`, and no other reason type. All had valid UniParc
identity and one exact-five-key top-level shape: `entryType`,
`primaryAccession`, `uniProtkbId`, `inactiveReason`, and
`extraAttributes`. The MERGED records were
`A0A2U8U0K3 → P18173` (`UPI000A0F4040`) and
`A0A8N4L368 → A0A034VJ86` (`UPI001114BBC8`), each with one target. Its
scan-manifest digest is
`sha256:4d734dd881829450178ed260ef331f7c3a21cdf0006f14ad3daa886c36125458`.
The earlier gapped request also observed `A0A034VJ94` as `DELETED` with
`UPI000453BEA2`. These observations justify the closed union but are only
read-only schema diagnostics: they are neither positive/cutover artifacts nor
fixed cardinality requirements for a future live response.

A later final-code full-set diagnostic completed in `679.154s` and observed
`37,772 = 32,176 active + 5,596 inactive`, with
`5,594 DELETED + 2 MERGED`, `378` ordered response digests, release `2026_02`,
and `2,561` length-filtered hits. Its full digests were score-filter input CSV
`sha256:c4f1e134c4e38fcda5424706544cccf0bf65b4187be2ce6d2f30114aeaf69b8f`,
provider metadata
`sha256:9deaebcf2c674cc8a7af52c1c00384fe2798b6d364f7d09e50c002abdcc89109`,
filtered hits CSV
`sha256:6a2aa371c2c366c9f539e23e4df9c6e1528c735be8515be5bff7bf2031237d67`,
and join manifest
`sha256:d768beb08f1bf5e5905e63249db352e1bcfe3e9eaea2d5be871e3adba39d8bca`.
These are ordinary read-only diagnostic outputs, not sealed/cutover artifacts,
and they cannot be adopted into either required positive attempt.

For each cutover-eligible positive that reaches UniProt,
`scientific_checks.sequence_join.uniprot_raw_response_artifact_id` must resolve
to one artifact in the exact formal `uniprot_fetch` operation outputs and in
that operation's UniProt provider receipt, with matching artifact provenance
and digest. The network-free verifier accepts the closed four-key
`provider_raw_http_response_set@1` envelope and closed eight-key response rows,
then validates strict JSON, canonical base64, byte size, response order/status,
body digest and the ordered metadata response-digest chain. Each sanitized
header map must carry one identical non-empty `x-uniprot-release` matching
metadata. `x-uniprot-release-date` is either absent on every page with null
metadata, or present identically on every page and equal metadata; partial or
drifting dates fail closed.

The verifier uses the engine sanitizer to rebuild an exact
requested/primary raw-result-to-metadata bijection. It permits unrelated future
raw result fields only when the complete sanitized non-sequence object is
reproduced by `provider_metadata` and `record_digest` binds the complete
sanitized result; the observed exact-five inactive shape is diagnostic, not a
future raw schema lock. Active raw sequence is
normalized with `strip().upper()`, checked for protein symbols and exact raw
length, and must reproduce metadata sequence length/digest before the existing
metadata-to-FASTA join is recomputed. Inactive raw results forbid `sequence`
and `entryAudit` and must reproduce the exact DELETED reason or MERGED
non-follow annotations.

The provider receipt `request_digest` must exactly equal the formal operation
`params_digest`, and that params digest must be reproduced from the sealed
canonical request parameters. The UniProt scientific output set is exactly
three distinct artifacts and roles: `uniprot_raw_response`,
`uniprot_metadata`, and `uniprot_sequences`. The AOX artifact-role map,
formal completed operation `outputs`, and completed UniProt provider receipt
`artifact_ids` must each contain that same exact three-id set once, with no
diagnostic request/observation/error artifact mixed into it. All three artifacts
must have `scope=formal`, `origin=operation`, provenance bound to the same
`uniprot_fetch` operation, and content digests equal to their operation output
refs. A re-sealed but differently scoped, role-swapped, extra, missing, or
duplicate set fails closed.

The canonical join first verifies a non-empty ordered provider
`response_digests` list, recomputes `aggregate_response_digest` from its
canonical JSON, requires every record `response_digest` to crosslink into that
list, and recomputes every inactive `record_digest` from its exact
`provider_metadata`. It then emits the exact count fields
`input_hit_count`, `uniprot_record_count`,
`uniprot_active_record_count`, `uniprot_inactive_record_count`,
`uniprot_inactive_deleted_record_count`,
`uniprot_inactive_merged_record_count`, `output_hit_count`,
`inactive_excluded_count`, `inactive_deleted_excluded_count`,
`inactive_merged_excluded_count`, and `length_rejected_count`. They must close
as input = all UniProt records = active + inactive, inactive = deleted + merged
= inactive excluded, each reason count = its excluded count, and active =
output + length rejected. `identity_mappings[]` uses
`status=active_sequence` for active records and `status=inactive` for both
inactive variants. An inactive mapping keeps exact requested/primary identity,
`identity_replaced=false`, UniParc and response/record digests, plus the same
closed nested `inactive_reason` object used by the provider. MERGED replacement
annotations retain `identity_replaced=false` and `target_followed=false`; no
mapping field grants sequence or fetch authority.

After a sandbox provider request draft exists, a `PipelineSdkFailure` seals the
exact request/observation/error diagnostic trio through the sandbox artifact
boundary and retains the original canonical failure with safe artifact refs.
It neither retries/replays the operation nor changes the fixed 17 normalized
deliverables.

Do not switch this workflow to UniProt asynchronous ID Mapping. These inputs are
already primary UniProt accessions; async mapping would add durable job handles,
submit/poll/result recovery, idempotency, approval and verifier/schema changes
without changing the scientific identity. That cross-layer migration is outside
this Goal. Bounded search queries inside the one operation are the current
fail-closed contract and do not authorize replay of a completed UniProt call.

Provider, registration, and fetch responses are deliberately rich provenance
envelopes. The same artifact can therefore appear in a canonical direct list
and again in a nested explanatory projection. Executor source MUST use the
installed strict selectors below instead of recursively walking an envelope or
guessing its shape:

```python
ncbi_file = artifacts.provider_file_ref(
    ncbi_operation,
    relative_path_suffix="/provider_parsed/proteins.fasta",
)
registered_reference = artifacts.registered_artifact_ref(
    artifacts.register(
        "/workspace/output/aox_hmm/AOX_ref21.fasta",
        kind="sequence",
        format="fasta",
    )
)
reference_stage = workspace.stage_artifact(
    registered_reference["artifact_id"],
    workspace_path="aox_hmm/AOX_ref21.fasta",
)
mafft_operation = bio_tools.mafft(
    input_fasta=reference_stage,
    placement=workspace,
    expected_outputs=[
        {
            "path": "bio_tools/mafft/alignment.fasta",
            "kind": "sequence",
            "format": "fasta",
        }
    ],
)
mafft_output = artifacts.fetched_output_ref(
    workspace.fetch_outputs(mafft_operation),
    declared_output_path="bio_tools/mafft/alignment.fasta",
)
```

The fixed AOX runner declarations use the same closed pairs: MAFFT and
HMMalign FASTA are `sequence/fasta`; hmmbuild HMM is `result/hmm`; CD-HIT
clustered FASTA is `sequence/fasta` and its membership is `result/csv`. The
Host may infer an omitted pair from its fixed template, but any explicit value
must match exactly. An explicit unknown kind such as `model` fails as
`artifact_kind_invalid`, and a valid-but-wrong kind/format pair fails as
`bio_tool_output_contract_mismatch`, both before runner dispatch.

The three selectors above are mutually exclusive by response origin:
`provider_file_ref` consumes a provider operation response,
`fetched_output_ref` consumes `workspace.fetch_outputs(...)`, and
`registered_artifact_ref` consumes only the direct response of
`artifacts.register(...)`. The first two already return terminal canonical
refs. Do not chain selectors, pass their result into
`registered_artifact_ref`, or construct a synthetic registration envelope.

`provider_file_ref` reads only
`result_summary.transcript_manifest.files`, `registered_artifact_ref` reads only
the closed registration projection, and `fetched_output_ref` reads only the
top-level `fetch_refs` list. Each requires one exact match plus canonical
artifact and SHA-256 identities. Missing, duplicated, malformed, or nested-only
data fails locally with a non-retryable structured SDK error. None of these
helpers performs provider I/O, runner execution, artifact registration, hidden
fallback, or recursive selection.

After every controlled operation completes, persist its full response in the
same sandbox's mutable `/workspace/work` before doing downstream local parsing.
Before the first operation-bearing run, resolve uncertain helper contracts from
the already selected SOP plus controlled `docs.search` / `docs.read` content.
Do not use `sandbox.exec` as a read-only environment-inspection shortcut: every
otherwise-valid invocation that reaches source preflight, including `python -c`,
package/signature inspection, and diagnostics, first snapshots the entire
non-empty `/workspace/src` tree. Earlier request, workspace, layout, and runtime
validation can fail before source preflight. If runtime
introspection is still necessary, author that inspection source explicitly
under `/workspace/src` before executing it. An empty tree fails as
`source_snapshot_empty` before `SandboxRun` or process creation. A completed
operation MUST NOT be replayed merely because response selection,
serialization, or later Python source failed. Under bundle/probe `@1`/`@2`, a
terminal failed sandbox run makes the attempt ineligible and its effects cannot
be adopted by a later run: retain checkpoints for failure evidence, start no
further controlled operation, explicitly fail the task, and use a fresh
blank-world attempt. `/workspace/work` checkpoints are agent working state, not
scientific evidence or cross-run adoption authority. Supporting explicit
same-attempt cross-run adoption remains proposal-only in
[canonical scientific chain adoption and attempt closure](../architecture-proposals/canonical-scientific-chain-adoption-and-attempt-closure.md).

The formal scientific closure always reaches `bio.ncbi_fetch_proteins`,
`bio_tools.mafft`, `bio_tools.hmmbuild`, and
`bio.hmmer_search(database="refprot")`. It reaches `bio.uniprot_fetch` only
when the canonical HMMER score filter yields a non-empty accession set,
`bio_tools.hmmalign` only when the post-UniProt target FASTA is non-empty, and
`bio_tools.cdhit` only when at least one target passes the motif rule. The
executor still uses `hpc.workspace`, `hpc.stage_artifact`,
`hpc.fetch_outputs`, and `artifacts.register` wherever the reached operation
requires those Host-supervised mechanics.

The current trusted-Host containment has an AOX-specific timeout hierarchy.
EBI HMMER polling remains bounded at `1800s`; every `sandbox.exec` invocation
whose source may reach `bio.hmmer_search` MUST request
`timeout_seconds=3600` under `s09.exec_policy.v2`; the formal live session and
public request are bounded at no less than `7200s`. Short inspection or
source-repair commands that cannot reach HMMER may use shorter bounds, but they
still require an explicitly authored non-empty source tree and receive their
own source snapshot. This
fixes a world constraint, not an execution graph: the agent remains free to
author, inspect and repair source, but an undersized HMM-capable command fails
before approval/provider dispatch and never authorizes a duplicate operation.
The `1800s` value bounds polling rather than claiming an aggregate bound over
all result-page transfer. Any timeout still fails closed without hidden replay.

This is a branch-derived evidence closure, not a unique execution order and not
permission to omit a reached dependency. The offline verifier derives the
branch from sealed raw/parsed and calculated artifacts, then requires the exact
formal operation set for that branch and rejects extra or hidden failed
operations. The agent may batch, inspect, retry within the bounded policy, or
stop at a proven empty prerequisite without asking the harness to invent an
alternate route.

"Retry within the bounded policy" means provider/runtime attempts that remain
inside one durable controlled-operation identity. It does not authorize a new
controlled operation for a scientific method that the formal session already
reached. The live cutover driver checks this exact-operation budget before
approval, rejects a duplicate before provider/runner dispatch, and stops
approving later scientific work after any controlled operation reaches
`failed` or `recovery_failed`. Local source repair remains allowed when it
reuses the already completed response and artifact identities.

### Pinned SDK calculation and runner projection

The calculation identities above are executable contracts, not prose that may
be approximated. When a branch reaches one of them, executor source MUST import
and call the installed `openzyme_pipeline.aox_*` implementation and write the
result through its canonical serializer. Reimplementing the formula, replacing
it with percent identity, or emitting schema-shaped hand-written rows is a
scientific contract violation. This fixes calculation identity only; the agent
remains free to choose legal batching, ordering, inspection, retry and source
layout.

| scientific output | installed callable | canonical serializer(s) |
|---|---|---|
| 13-record HMM reference | `openzyme_pipeline.aox_reference.select_hmm_reference_set` | `result.to_fasta()`, `result.metadata_json()` |
| coordinate reference | `openzyme_pipeline.aox_reference.select_scoring_reference` | `result.to_fasta()`, `result.metadata_json()` |
| reference-plus-target scoring input | `openzyme_pipeline.aox_reference.assemble_scoring_input` | `result.to_fasta()`, `result.metadata_json()` |
| HMMER score-filtered accessions | `openzyme_pipeline.aox_hmmer.parse_and_filter_csv` | `result.to_csv()`, `result.metadata()` |
| UniProt identity/length join | `openzyme_pipeline.aox_sequence_join.join_score_filtered_accessions` | `result.hits_csv()`, `result.target_fasta()`, `result.metadata()` |
| motif reference-coordinate score | `openzyme_pipeline.aox_motif.score_aligned_fasta` | `result.to_csv()`, `result.metadata()` |
| candidate similarity graph | `openzyme_pipeline.aox_similarity.build_similarity_graph` | `result.nodes_csv()`, `result.edges_csv()`, `result.manifest_json()` |

The following is the stable minimum call map for executor-authored source. The
first positional arguments are bytes read from the exact materialized or
fetched artifacts. For a cutover-eligible run, every shown `expected_*_digest`
MUST be supplied from the bound artifact or pinned contract rather than omitted
because the Python default is `None`.

```python
aox_reference.select_hmm_reference_set(
    ncbi_fasta,
    *,
    expected_contract_id,
    expected_contract_digest,
    expected_implementation_digest,
    expected_input_digest,
)
# -> result.to_fasta(), result.metadata_json()

aox_reference.select_scoring_reference(
    ncbi_fasta,
    *,
    expected_contract_id,
    expected_contract_digest,
    expected_implementation_digest,
    expected_input_digest,
)
# -> result.to_fasta(), result.metadata_json()

aox_reference.assemble_scoring_input(
    scoring_reference_fasta,
    post_uniprot_target_fasta,
    *,
    expected_contract_id,
    expected_contract_digest,
    expected_implementation_digest,
    expected_scoring_reference_input_digest,
    expected_target_input_digest,
)
# -> result.to_fasta(), result.metadata_json()

aox_hmmer.parse_and_filter_csv(
    parsed_hits_csv,
    *,
    expected_contract_id,
    expected_contract_digest,
    expected_implementation_digest,
    expected_input_digest,
)
# -> result.to_csv(), result.metadata()

aox_sequence_join.join_score_filtered_accessions(
    score_filtered_csv,
    uniprot_fasta,
    uniprot_metadata_json,
    *,
    expected_contract_id,
    expected_contract_digest,
    expected_implementation_digest,
    expected_hmmer_contract_id,
    expected_hmmer_contract_digest,
    expected_hmmer_implementation_digest,
    expected_score_filtered_csv_digest,
    expected_uniprot_fasta_digest,
    expected_uniprot_metadata_digest,
)
# -> result.hits_csv(), result.target_fasta(), result.metadata()

aox_motif.score_aligned_fasta(
    scoring_alignment_fasta,
    *,
    expected_contract_id,
    expected_contract_digest,
    expected_implementation_digest,
    expected_input_digest,
)
# -> result.to_csv(), result.metadata()

aox_similarity.build_similarity_graph(
    candidate_fasta,
    cdhit_membership_csv,
    *,
    threshold_ppm,
    empty_result_reason,
    expected_calculation_id,
    expected_calculation_digest,
    expected_implementation_digest,
    expected_candidate_fasta_digest,
    expected_membership_digest,
)
# -> result.nodes_csv(), result.edges_csv(), result.manifest_json()
```

Use `empty_result_reason=None` for a non-empty graph and the reached stable
reason for an empty graph. Do not guess alternative keyword names, pass provider
metadata in place of its JSON bytes, or serialize dataclass internals by hand.

Provider files are selected from the unique
`result_summary.transcript_manifest.files` entry whose `relative_path` has the
required suffix: NCBI `/provider_parsed/proteins.fasta`, EBI HMMER
`/provider_parsed/parsed_hits.csv`, and UniProt
`/provider_parsed/sequences.fasta` plus `/provider_parsed/metadata.json`. Do not
select positional `artifact_ids`, `adapter_result_envelope` lists, or a file
with merely a similar basename.

Those four leading-slash strings are logical manifest suffixes, not Host
locators. The public evidence scanner permits exactly
`/provider_parsed/proteins.fasta`, `/provider_parsed/parsed_hits.csv`,
`/provider_parsed/sequences.fasta`, and `/provider_parsed/metadata.json`; it
does not allow the provider directory generally. While scanning a sealed Python
source tree it also recognizes the lexical Python path-join form such as
`Path("aox_hmm")/p.name` instead of misclassifying `/p.name` as an absolute Unix
path. This is a narrow source-syntax exception: arbitrary text such as
`prefix)/p.name`, an unknown suffix such as `/provider_parsed/private.txt`,
traversal, `/home/...`, `/tmp/...`, and every other unrecognized absolute path
still fail closed. Existing logical `/workspace`, `/openzyme/control.sock`, and
closed public `/v3/...` routes remain unchanged.

The runner templates likewise own their output paths. The caller declares the
exact path set below, calls `hpc.fetch_outputs`, and selects each artifact from
the unique `fetch_refs` row whose `declared_output_path` is equal to the fixed
path. The normalized `aox_hmm/*` deliverables are later derived or copied from
these fetched artifacts; they are not caller-defined runner paths.

| SDK operation | exact runner output path set |
|---|---|
| `bio_tools.mafft` | `bio_tools/mafft/alignment.fasta` |
| `bio_tools.hmmbuild` | `bio_tools/hmmbuild/model.hmm` |
| `bio_tools.cdhit` | `bio_tools/cdhit/clustered.fasta`, `bio_tools/cdhit/clusters.csv` |
| `bio_tools.hmmalign` | `bio_tools/hmmalign/aligned.fasta` |

`bio.hmmer_search(database="refprot")` must bind the exact fetched hmmbuild
artifact id and its exact `content_digest`; a copied filename or model-shaped
bytes without that artifact/digest edge cannot satisfy the operation identity.

## Required provider quorum

Cutover eligibility requires one terminal, cache-bypassed aggregate receipt for
each required provider, bound to the same formal attempt by invocation,
controlled-operation, request/response and sealed-artifact digests:

- PubMed supplies the required literature evidence. At least one accepted
  source ref has a numeric PMID present in the sealed parsed response. A DOI is
  retained only when PubMed supplies it; absence is not filled by a model or an
  enrichment provider.
- NCBI supplies one exact 14-record protein FASTA aggregate: the 13 HMM-model
  references below plus coordinate reference `AAB57849.1`. It is never an
  empty-success route. Versioned selection calculations derive the 13-record
  model input and the single-record coordinate input from the same sealed
  aggregate.
- EBI HMMER REST supplies the real `refprot` search receipt and parsed numeric
  hit provenance. A schema-valid real no-hit response is distinct from a
  provider failure.
- UniProt supplies candidate identity, reviewed status, release/version,
  retrieval time, response digest, and sequence digest when the HMMER
  score-filtered accession artifact is non-empty. When that artifact is empty,
  the formal path MUST NOT call UniProt; a strict
  `provider_upstream_empty_receipt@1` proves the trigger and
  `provider_io_performed=false` without fabricating an invocation, request, or
  response digest.

The researcher may perform bounded iterative PubMed searches; the harness does
not force one query, stop at the first success, or infer a preferred result by
timestamp or result count. Before `task.finish`, the researcher MUST explicitly
adopt exactly one succeeded, source-bearing PubMed evidence artifact by placing
exactly one `artifact:<id>` for provider `pubmed` in `evidence_refs`. Zero or
multiple adopted PubMed artifacts is ambiguous and fails closed. The selected
artifact, its one succeeded research invocation, numeric-PMID source refs, and
the researcher task MUST have identical task/lane lineage; `lane_id=None` is
valid only when it is identical across the whole chain. Natural-language use of
"primary" is not authority. The reporter MUST cite a PMID/source from this
selected artifact. Other exploratory, empty, failed, or superseded invocations
remain durable control-plane history, but the current `@1` cutover bundle seals
only the explicitly adopted provider receipt. A future complete-history proof
is proposal-only in [canonical research evidence adoption and invocation
history](../architecture-proposals/canonical-research-evidence-adoption-and-invocation-history.md).

Semantic Scholar and Tavily are enrichment only. Their rate limit, absence, or
bounded retry exhaustion is recorded as `degraded` and disclosed in the
report; it does not erase complete PubMed evidence. Conversely, enrichment
success never compensates for missing or invalid PubMed, NCBI, EBI HMMER, or a
reached UniProt operation. No provider may be replaced with fixture, cached,
synthetic, or model-generated evidence.

## Scientific prerequisites

The HMM-model input contains these fixed 13 reference accessions:

```text
AAC72747.1
KDQ24956.1
9AVH_A
XP_014653549.1
KIS68002.1
XP_003660923.1
AMW87253.1
AFP17823.1
WP_190019735.1
WP_138089821.1
WP_176407597.1
CAQ19343.1
CAQ19344.1
```

The same formal NCBI request also contains the distinct coordinate reference
`AAB57849.1`, so its exact request set has 14 identities. The sealed provider
aggregate is not itself the HMM training file. From that aggregate:

- `aox_hmm_reference_set_selection@1` emits the exact 13-record
  `AOX_ref21.fasta` in contract order;
- `aox_reference_selection@1` emits only
  `AOX_coordinate_reference_AAB57849.1.fasta`;
- `AAB57849.1` MUST NOT enter the 13-record MAFFT/hmmbuild model input.

The search route is EBI HMMER REST against `refprot`. Candidate filtering uses
observed provider fields only: sequence length from 650 through 700 inclusive
and HMM score strictly greater than 200.

NCBI must prove a one-to-one requested-to-resolved mapping for every one of the
14 identities, including the exact PDB chain request `9AVH_A` and coordinate
reference `AAB57849.1`. Each resolved FASTA record keeps its requested
accession, provider header/identity, normalized sequence digest, raw-record
digest, and the aggregate FASTA digest. Missing, unexpected, duplicate, or
ambiguously resolved records invalidate both derived reference artifacts.

Every EBI `refprot` candidate has a primary UniProt accession. Cross-database
identities are append-only annotations: an NCBI, EBI, or UniProt mapping cannot
silently overwrite another identifier or sequence. When mapped sequence bytes
differ, preserve both digests and require an explicit selection before the
selected bytes enter alignment, scoring, clustering, or reporting.

The HMMER-to-UniProt chain is fixed even though the agent chooses legal
batching and inspection strategy:

1. the EBI HMMER parsed artifact has the exact 11-column provider schema and
   preserves page, hit index, numeric fields, raw-page/raw-hit/parsed-row
   digests;
2. `hmmer_score_filtered_accessions@1` retains only canonical UniProt
   accessions whose provider score is strictly greater than `200` and emits
   `hmmer_score_filtered_accessions.csv`; the primary accession body must
   satisfy UniProt's official 6- or 10-character format, while an explicit
   isoform suffix remains identity-bearing and is never silently collapsed;
3. only a non-empty exact artifact/accession set may be bound as the
   `bio.uniprot_fetch` source-hit input;
4. `aox_sequence_length_join@2` verifies that active sequence records plus
   typed exact-requested inactive `DELETED|MERGED` records exactly partition
   the HMMER accession set, deterministically excludes both inactive variants
   without following a merged target before length filtering, then applies
   inclusive `650..700` only to exact active UniProt sequence bytes and emits
   `target.fasta` plus `hits_len650_700_200.csv`. Its metadata makes active,
   inactive-reason-excluded, length-rejected and output counts plus sorted
   mappings offline-verifiable.

`aox_scoring_input_assembly@1` then places the single AAB coordinate reference
first and appends post-UniProt targets in lexical target-id order to emit
`AOX_scoring_input.fasta`. For a non-empty target set, HMMalign consumes exactly
the built `AOX_ref.hmm` plus this scoring input. For an empty target set,
HMMalign is omitted and `aox_reference_only_scoring_alignment@1` materializes
the already validated AAB-only scoring input as
`AOX_scoring_alignment.fasta`.

The downstream motif filter is the immutable
`aox_motif_rule_score@1` calculation against the one-based ungapped reference
coordinates of `AAB57849.1`. It uses exact integer tenths and passes at `336`;
`33.6` is only the fixed one-decimal presentation. The executor must preserve
the scoring alignment and emit the scorer's canonical rows, contract digest,
implementation digest, input digest, and normalized alignment digest. This is
a reference-coordinate heuristic, not an experimental activity prediction.
Missing reference coordinates or digest drift returns
`scientific_prerequisite_missing`; do not copy HMM scores into motif scores or
construct pass decisions.

Its aligned FASTA parser binds `hmmer_afa_alignment_canonicalization@1` and
hashes exact pre-canonical bytes as `input_digest`. Physical segments split
only on LF; one immediately preceding CR is removed only from an LF-terminated
segment, while lone/repeated/other CR fail closed. Header `>` must occupy raw
column 0. Explicit empty lines are ignored, but every non-empty sequence line
must match raw ASCII `^[A-Za-z.-]+$` before uppercase normalization; any
leading/trailing/internal whitespace, Unicode whitespace, `ß`, `ſ`, or other
non-ASCII input is rejected. After validation, ASCII residues uppercase and
HMMER insert-column `.` gaps canonicalize to `-`. Thus `.`/`-` or case-only
inputs retain distinct raw digests but identical normalized alignment, residue
observations and score rows.

A final-code read-only `/tmp` preflight parsed a real `12,273,402`-byte HMMER
AFA with `2,562` records at width `4,700`: canonical dot count zero, `517`
total passes including `AAB57849.1`, and `516` non-reference passes. This
diagnostic is not sealed, blank-world, operation-bound, report-backed, or
cutover evidence and cannot be adopted into a live attempt.

Likewise, every similarity value and cluster id must come from declared tool
output or a versioned, auditable calculation. Do not emit constant `0.91` edges
or a constant cluster id.

The current exact similarity implementation packs the former lexical
`(score,matches,aligned_residues)` state using radix `max(m,n)+1`, which is
mathematically comparison-equivalent and preserves the published
score/count/identity decision. The pinned
`biopython_trace_guarded_numpy_gotoh@1` backend uses
Biopython `1.87` and NumPy `2.4.4`; packed values may cross binary64 only after
their strict `<2^53` bound and integral result are verified. Its first optimal
trace is inspected, and only an adjacent horizontal/vertical gap-state switch
activates the declared exact-`int64`
`numpy_three_state_gap_switch_correction@1`. The correction is part of this
calculation identity, not a fallback. Import/version, algorithm, numeric,
trace, or correction drift fails closed; there is no alternate library,
version, pure-Python, or scientific fallback.

The reference recurrence state order records tie provenance only. This graph
contract publishes score/match/aligned-residue counts and never promises
alignment coordinates or a selected path; the trace inspection is internal.
Publishing either later requires a new calculation id and an explicit trace
contract.

Pair order is lexical; fewer than `128` pairs are serial. At least `128` pairs
are parallel-eligible with worker count equal to the minimum of pair count,
`16`, affinity (or `cpu_count` only when affinity is unavailable), and every
available cgroup v2/v1 CPU quota divided by period and rounded up. Present but
unreadable, incomplete, or malformed cgroup limits fail closed. Worker count
`1` selects serial before execution, while a larger count uses an
output-order-preserving process pool with chunks of `64`. Pool failure after
that parallel branch begins returns `similarity_parallel_execution_failed` and
never silently falls back to serial. Within one offline-verifier invocation
the graph is recomputed once and the same result is reused for node, edge, and
manifest closure; this is invocation-local work sharing, not a cross-attempt
result cache or new evidence authority.

Reference validation used NumPy `2.4.6`, whereas the cutover runtime pin is
NumPy `2.4.4`. They are intentionally recorded as different environments, with
no patch-version fallback. The final r26 current-backend diagnostic receipt is
`sha256:ace8baa8bfa070a621186d7b3db3acddcdf39abe26070e72270fc727b0017b5e`.
Its two independent exact-cutover-NumPy-`2.4.4`, 2-CPU/2-worker runs processed
516 nodes, 132,870 pairs, and 13,778 edges with byte-identical current-contract
outputs; after normalizing only required pin fields and pin-induced manifest
closure, both are byte-identical to the historical pure-v3 output. It records
correction activation as unavailable because production exposes no counter and
wrapping was forbidden, rather than inventing zero. This is not a direct
full-set `2.4.6`/`2.4.4` patch A/B and does not make `2.4.6` an allowed runtime.
The receipt, earlier pure-v3 receipt, and temporary 2-CPU calibration remain
ordinary unsealed non-cutover diagnostics; they close the knowledge-pin gate,
not either live positive attempt or campaign GO.

No real HMM hits, no fetched target sequences, or no candidates after the real
filters is a legitimate scientific empty result. Record it as
`scientific_outcome.status="empty"` with one of the stable reached reasons and
do not substitute reference or probe sequences to make the result non-empty:

| derived branch | stable reason | formal operations omitted |
|---|---|---|
| HMMER parsed/score-filter empty | `no_hmmer_hits` or `no_filtered_hmmer_accessions` | UniProt, HMMalign, CD-HIT |
| UniProt length join empty | `no_candidates_after_length_filter` | HMMalign, CD-HIT |
| motif filter empty | `no_candidates_after_motif_filter` | CD-HIT |
| non-empty candidates | n/a | none of the reached scientific chain |

Under this `2.0.0` contract, an empty result is a healthy, cutover-eligible
execution outcome only when every reached provider/tool receipt is terminal and
valid, the exact omitted set matches the derived branch, the independent
known-positive provider/HPC probe covers omitted capabilities, canonical empty
artifacts validate, all product tasks exit explicitly, and the published report
states that no candidates were discovered. Operational success remains
separate from scientific discovery. A failed probe, provider error, schema
drift, hidden failed operation, or incomplete evidence is `failed`/`degraded`,
never a healthy empty result.

A zero-record FASTA is represented only by an exact zero-byte regular file and
registered with `validation_profile="fasta_zero_records@1"`. Its metadata must
contain one stable `empty_result_reason` and the versioned
`derivation_contract_id` that actually produced the empty branch, such as
`aox_upstream_empty_materialization@1`, `aox_sequence_length_join@2`,
`aox_motif_candidate_filter@1`, or `canonical_empty_cluster_membership@1`.
Without that explicit profile the normal FASTA validator still requires real
records. Header-only files, whitespace, `>EMPTY\nX`, `NO_*` text, placeholder
clusters, self-loop graph rows, and any other non-zero sentinel are invalid.
The profile proves only the byte shape and typed derivation claim; the offline
AOX verifier still recomputes the sealed catalog validation receipt, branch and
provenance before accepting it as healthy empty. A zero-byte sequence without
`openzyme_typed_empty_artifact_validation@1`, or with a receipt reason that
differs from the scientific outcome, is ineligible.

## Known-positive probe contract

The installed collector/verifier contract is `aox_known_positive_probe@2` with
`probe_id="independent_globin_provider_hpc_probe"`. This states implementation
availability only: no real `@2` attempt is considered passed until its sealed
attestation survives offline verification in the current campaign. An
`@1`/AAB-only probe cannot satisfy this pack because one sequence does not prove
the intended MAFFT/HMM build/alignment and cross-provider chain.

The bounded `@2` contract uses NCBI `NP_000509.1` and `NP_000549.1`, UniProt
`P68871` and `P69905`, and exactly six isolated controlled operations:

1. NCBI protein fetch, then MAFFT, then hmmbuild;
2. UniProt protein fetch, then protein CD-HIT at identity `1.0`;
3. one HMMalign that consumes the real HMM plus the real CD-HIT representative
   FASTA.

The probe has one isolated task, workspace, sandbox and source snapshot. It
must bind raw HTTP response-body digests, provider identities and all
input/output artifact edges. It does not repeat EBI HMMER because the formal
path always reaches that provider. Probe operations, bytes and conclusions
cannot appear in formal artifact roles, formal task/report claims or the AOX
scientific outcome.

The one operation-bearing probe source passes the two provider output roots as
complete literals `/workspace/output/provider/ncbi` and
`/workspace/output/provider/uniprot`. It must not interpolate a sandbox root
constant immediately before slash-prefixed suffixes: the sealed raw source is
itself public evidence, so an ambiguous suffix that resembles an unknown Host
absolute path fails attestation. This source-shape constraint does not grant a
new path authority or relax the public-safe scanner.

## Registered deliverable contract

A passed run registers at least these normalized final relative paths, all
derived from the current controlled-operation evidence:

- `aox_hmm/AOX_ref21.fasta`
- `aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta`
- `aox_hmm/AOX_scoring_input.fasta`
- `aox_hmm/target.fasta`
- `aox_hmm/AOX_ref.hmm`
- `aox_hmm/hits_raw.csv`
- `aox_hmm/hmmer_score_filtered_accessions.csv`
- `aox_hmm/hits_len650_700_200.csv`
- `aox_hmm/AOX_scoring_alignment.fasta`
- `aox_hmm/scored_ref_plus_hits.csv`
- `aox_hmm/AOX_candidates.fasta`
- `aox_hmm/AOX_candidates_cdhit85.fasta`
- `aox_hmm/AOX_candidates_cdhit85.clusters.csv`
- `aox_hmm/nodes.csv`
- `aox_hmm/edges_similarity.csv`
- `aox_hmm/similarity_graph_manifest.json`
- `aox_hmm/execution_summary.json`

Each path has one canonical artifact wire pair. `kind` remains the closed
catalog class while `format` carries the concrete encoding; semantic labels
must go in metadata. Online evidence copies, cache hits, controlled fault
targets and the offline verifier bind the exact path and pair under
`aox_fixed_deliverable_artifact_contract@1`; a renamed path, missing contract
binding or kind/format drift makes the attempt ineligible.

| Normalized path | `kind` | `format` |
| --- | --- | --- |
| `aox_hmm/AOX_ref21.fasta` | `sequence` | `fasta` |
| `aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta` | `sequence` | `fasta` |
| `aox_hmm/AOX_scoring_input.fasta` | `sequence` | `fasta` |
| `aox_hmm/target.fasta` | `sequence` | `fasta` |
| `aox_hmm/AOX_ref.hmm` | `result` | `hmm` |
| `aox_hmm/hits_raw.csv` | `result` | `csv` |
| `aox_hmm/hmmer_score_filtered_accessions.csv` | `result` | `csv` |
| `aox_hmm/hits_len650_700_200.csv` | `result` | `csv` |
| `aox_hmm/AOX_scoring_alignment.fasta` | `sequence` | `fasta` |
| `aox_hmm/scored_ref_plus_hits.csv` | `result` | `csv` |
| `aox_hmm/AOX_candidates.fasta` | `sequence` | `fasta` |
| `aox_hmm/AOX_candidates_cdhit85.fasta` | `sequence` | `fasta` |
| `aox_hmm/AOX_candidates_cdhit85.clusters.csv` | `result` | `csv` |
| `aox_hmm/nodes.csv` | `result` | `csv` |
| `aox_hmm/edges_similarity.csv` | `result` | `csv` |
| `aox_hmm/similarity_graph_manifest.json` | `result` | `json` |
| `aox_hmm/execution_summary.json` | `result` | `json` |

`model`, `alignment`, `table`, and `graph` are never valid `kind` values.
Only the scientifically derived empty variants of `target.fasta`,
`AOX_candidates.fasta`, and `AOX_candidates_cdhit85.fasta` may be exact
zero-byte files; they retain `sequence/fasta` and additionally require
`validation_profile=fasta_zero_records@1`, a stable reason, and the applicable
versioned derivation contract. Other final FASTA files remain non-empty.

The normalized CSV schemas are:

- `hits_raw.csv`: the exact HMMER provider-parsed columns `target`,
  `accession`, `evalue`, `score`, `page`, `hit_index`, `evalue_numeric`,
  `score_numeric`, `raw_page_digest`, `raw_hit_digest`, and
  `parsed_row_digest`; it carries no downstream sequence/length truth
- `AOX_ref21.fasta`: exact 13-record output of
  `aox_hmm_reference_set_selection@1`
- `AOX_coordinate_reference_AAB57849.1.fasta`: exact one-record output of
  `aox_reference_selection@1`
- `hmmer_score_filtered_accessions.csv`: canonical seven-column output of
  `hmmer_score_filtered_accessions@1`; it carries no sequence or length field
- `hits_len650_700_200.csv`: canonical output of
  `aox_sequence_length_join@2`, including active UniProt-derived sequence and
  excluding typed inactive `DELETED|MERGED` identities before the length
  filter without following replacement targets
- `AOX_scoring_input.fasta`: exact output of
  `aox_scoring_input_assembly@1`, with AAB first and target ids sorted
- `AOX_scoring_alignment.fasta`: HMMalign output for a non-empty target set, or
  the exact AAB-only scoring input under
  `aox_reference_only_scoring_alignment@1` for a derived empty target set
- `scored_ref_plus_hits.csv`: exactly the canonical columns declared by
  `openzyme_pipeline.aox_motif.CANONICAL_COLUMNS`, including exact tenths,
  fixed-decimal presentation, pass decision, per-coordinate residues, sequence
  and alignment digests, plus contract and implementation identities
- `AOX_candidates_cdhit85.clusters.csv`: one row per candidate member under
  `cdhit_cluster_membership@1`, with `cluster_id`, `member_id`,
  `representative_id`, `is_representative`,
  `identity_to_representative`, and `member_length`
- `nodes.csv` and `edges_similarity.csv`: the canonical node/edge schemas of
  the versioned real-sequence similarity calculation; every row carries its
  sequence, membership, calculation, and schema identities. The authoritative
  calculation and schema contract is
  [aox-sequence-similarity-v1.md](aox-sequence-similarity-v1.md); do not copy its
  column list into an independent implementation.
- `similarity_graph_manifest.json`: the canonical closure over candidate and
  membership input digests, schema/calculation/implementation identities,
  threshold, node/edge digests and counts, plus explicit empty-result semantics

`execution_summary.json` records HMMER parsed/score-filtered, UniProt joined,
scored, candidate, representative and graph counts; exact motif threshold
fields; `hmmer_database="refprot"`; the five reference/filter/join contract
identities above; required/enrichment provider status; normalized final paths;
scoring, membership, and similarity schema/digest identities; the derived
scientific branch; exact omitted formal roles; and any upstream-empty skip
receipt identity. A scientific empty result uses header-only
candidate/membership/node/edge outputs plus a stable non-empty
`empty_result.reason`. The summary is checked against sealed bytes and cannot
select its own branch or turn missing, fixture, constant, or synthetic evidence
into success.

## Strategy guidance

The executor should confirm the selected manifest and pinned document digests,
inspect its persistent workspace, and use dry-run/approval information when
useful. All real provider and HPC/tool operations go through the SDK with
catalog artifact ids and Host-supervised staging/fetch. Actual registered
outputs are parsed before normalized artifacts are registered. Missing fields,
malformed data, identity or digest drift, and absent scoring prerequisites stop
the affected path with a structured error. Task completion requires the
applicable non-empty or healthy-empty evidence closure; otherwise the agent
finishes it as blocked/failed with the observed evidence. These are acceptance
invariants, not a prescribed command sequence.

Provider and HPC SDK responses expose registered output ids through the current
adapter/result envelope, not Host paths. `artifacts.get` may be used to locate a
registered relative path; `artifacts.materialize` creates the authorized input
target. Never infer a storage path from a public payload.

## Scientific fail-closed matrix

The following conditions prohibit a cutover-eligible report or attempt bundle:

- workflow, knowledge, SDK, motif, similarity, image, provider, toolchain,
  operation, artifact, or report identity/digest drift;
- a missing/duplicate/mismatched NCBI identity, including unresolved
  `9AVH_A` or `AAB57849.1`, an NCBI aggregate that is not exactly the requested
  14, a model-reference selection that is not exactly the fixed 13, or a
  coordinate-reference selection that is not exactly AAB-only;
- missing PubMed PMID evidence, required-provider failure, malformed EBI HMMER
  fields, reuse of terminal-poll hits as page 1, cross-page `page_count` drift,
  a non-truncated raw-hit count unequal to terminal `stats.nreported`, HMMER
  score-filter drift, a reached but unbound UniProt accession, an incomplete
  active/inactive requested-set partition, `DEMERGED` or malformed/unknown
  inactive status, a noncanonical MERGED annotation or any followed/fetched
  replacement target, use of inactive/replacement/UniParc/HMMER sequence bytes,
  UniProt sequence/length join drift, or an unresolved cross-source sequence
  mismatch;
- HMMalign input that is not exactly the HMM plus assembled scoring input,
  AAB/model-reference conflation, a branch-incompatible extra operation,
  hidden failed operation, or an upstream-empty receipt containing fabricated
  provider I/O/request/response identity;
- missing reference coordinates, legacy scoring fields (`activity_score`,
  `seq_score`, `pass_rule`), synthetic sequence bytes, copied scores, constant
  cluster ids/edges, or graph/CD-HIT lineage that cannot be recomputed;
- a claimed healthy empty result without an independent successful probe,
  terminal required receipts, canonical empty schemas, and an honest published
  report;
- fixture/seeded/cache evidence, preloaded scientific roots, a replaced
  approval operation, non-explicit task exits, or a report/final answer not
  linked to the sealed evidence closure.

On any such condition, preserve the terminal failure/degradation evidence and
let the agent explain or retry within policy. The harness must not silently
rewrite the plan, add synthetic evidence, reopen an operation, or choose a
fallback workflow.
