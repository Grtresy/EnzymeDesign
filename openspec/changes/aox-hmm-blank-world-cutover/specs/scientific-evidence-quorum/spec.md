## ADDED Requirements

### Requirement: Required PubMed literature evidence
The AOX/HMM cutover workflow SHALL require at least one real PubMed record supporting the scientific context. Each accepted record MUST carry a PMID, provider identity, title, source locator, retrieval time, response digest, and available bibliographic fields; a DOI SHALL be recorded when PubMed supplies one and MUST NOT be invented when absent.

#### Scenario: Required literature quorum succeeds
- **WHEN** PubMed returns one or more schema-valid records and the report links its scientific claims to their source refs
- **THEN** the required literature quorum is `complete` and the sealed evidence contains only safe citation metadata, digests, and licensed content

#### Scenario: Required literature is unavailable
- **WHEN** PubMed fails, returns a malformed response, or returns no evidence for the bounded AOX query set
- **THEN** the workflow records the provider failure or empty result and cannot become cutover eligible

### Requirement: Explicit primary PubMed evidence adoption
The researcher MAY perform multiple bounded PubMed invocations while refining a scientific query. Before completing the research task, it SHALL adopt exactly one succeeded, cutover-eligible PubMed evidence artifact by including exactly one PubMed `artifact:<id>` in `task.finish.evidence_refs`. The selected artifact, its succeeded research invocation, every selected numeric-PMID source ref, and the researcher task SHALL share exact task and lane identity; a lane MAY be `None` only when it is `None` throughout the chain. The collector and verifier MUST NOT infer primary status from timestamps, first success, result count, natural-language summary, or report prose.

#### Scenario: Iterative searches adopt one primary receipt
- **WHEN** bounded research produces multiple PubMed invocations and the researcher adopts exactly one succeeded source-bearing PubMed artifact
- **THEN** only that artifact/invocation/source set supplies the canonical required provider receipt, while other invocations remain durable control-plane history

#### Scenario: Primary adoption is missing or ambiguous
- **WHEN** researcher `task.finish.evidence_refs` contains zero or more than one PubMed evidence artifact
- **THEN** collection fails closed with missing or ambiguous primary evidence and no cutover-eligible bundle is produced

#### Scenario: Nullable lane lineage is exact
- **WHEN** researcher task, selected invocation, selected artifact, and every selected source all carry `lane_id=None`
- **THEN** the optional lane scope is valid; any missing field, empty-string lane, or unequal lane value fails offline verification

### Requirement: Explicit enrichment degradation
Semantic Scholar and Tavily SHALL be enrichment providers rather than required quorum members. Retry exhaustion, rate limiting, absence, or empty results from an enrichment provider MUST be recorded as structured `degraded` evidence and MUST NOT erase valid PubMed evidence or be replaced by synthetic hits.

#### Scenario: Semantic Scholar is rate limited
- **WHEN** Semantic Scholar returns a persistent HTTP 429 after the shared retry budget is exhausted while required PubMed evidence is complete
- **THEN** the workflow continues with an explicit degraded provider record and the final report discloses the missing enrichment

#### Scenario: All literature providers fail
- **WHEN** PubMed is unavailable regardless of enrichment-provider status
- **THEN** the workflow fails closed and does not publish a cutover-eligible report

### Requirement: Provider error and retry taxonomy
All literature and bio provider calls SHALL use the shared invocation/adapter policy for bounded timeouts, `Retry-After`, transient retry, quota and schema errors. Provider-specific code MUST NOT implement an unbounded retry loop or a hidden fallback.

#### Scenario: Retryable transient failure recovers
- **WHEN** a provider returns a retryable transport or service error within the approved call budget and a later attempt succeeds
- **THEN** all attempts, retry timing, request identity, and final response digest are recorded under the same controlled operation

#### Scenario: Non-retryable schema drift occurs
- **WHEN** a required provider response lacks fields needed by its declared schema
- **THEN** the operation ends with a schema-drift failure and no inferred or model-generated replacement fields

#### Scenario: Persist a sandbox provider failure without replay
- **WHEN** a sandbox provider operation has established its request draft and then raises `PipelineSdkFailure`
- **THEN** the Host registers the exact request, observation, and error diagnostic artifacts through the same sandbox artifact boundary, rethrows the original canonical code/stage/retryability with safe artifact refs, and performs no retry, operation replay, fallback, or success reclassification

#### Scenario: Bound UniProt HTTP failure coordinates
- **WHEN** one UniProt query/page HTTP request fails inside the single controlled operation
- **THEN** the failure adds only query-batch index/count/start/count/digest and completed/requested page progress, and exposes no raw URL, accession values/list, or cursor

### Requirement: Reference and candidate identity separation
The workflow SHALL fetch exactly 14 NCBI protein identities in one sealed provider aggregate: the fixed 13 HMM-model reference accessions plus coordinate reference `AAB57849.1`. It SHALL derive the exact 13-record `AOX_ref21.fasta` with `aox_hmm_reference_set_selection@1`, derive the single-record `AOX_coordinate_reference_AAB57849.1.fasta` with `aox_reference_selection@1`, and SHALL use UniProt accession identity for EBI HMMER `refprot` candidate hits. Cross-database mappings MUST be explicit annotations and MUST NOT silently replace sequence bytes or identifiers.

#### Scenario: Seal and split NCBI reference sequences
- **WHEN** NCBI returns the exact 14-record provider set
- **THEN** the provider artifact records requested and resolved accessions, sequence digests, retrieval identity, provider request ids, missing/duplicate/extra mappings, and a sealed aggregate FASTA digest; the two selection artifacts are byte-for-byte recomputable from that aggregate, `AOX_ref21.fasta` contains only the fixed 13 HMM references, and the coordinate artifact contains only `AAB57849.1`

#### Scenario: Reject model-coordinate conflation
- **WHEN** `AAB57849.1` is missing from the NCBI aggregate, appears in the 13-record HMM training input, or the 13-record set is used as the coordinate-reference artifact
- **THEN** reference validation fails closed before MAFFT/hmmbuild or motif scoring produces cutover-eligible output

#### Scenario: Enrich a UniProt candidate
- **WHEN** an EBI HMMER hit resolves to a UniProt record
- **THEN** an active candidate records primary accession, reviewed status, UniProt release, retrieval time, sequence digest, mapping provenance, and response digest, while an exact-requested typed inactive `DELETED|MERGED` member records its reason-specific annotation, UniParc id, release/retrieval, response digest, and record digest without sequence, audit, replacement follow, or replacement fetch

#### Scenario: Mapping changes sequence identity
- **WHEN** a mapped UniProt sequence differs from the sequence already bound to another source identity
- **THEN** both identities and digests remain visible and the system requires an explicit selection rather than overwriting one with the other

### Requirement: Gap-free EBI HMMER result materialization
The EBI HMMER route SHALL retain `bio.hmmer_search.provider:v1` while binding `provider_config:ebi_hmmer:v2`. Configured result `page_size` SHALL default to and be capped at `1000`. Poll requests SHALL explicitly bind `page=1` and the configured page size, but the terminal payload SHALL be consumed only for status and non-negative `result.stats.nreported`; terminal-body hits MUST NOT become a result page. Result materialization SHALL always begin with a separate explicit page-1 request using the same page size and continue through the declared page count. Every result page SHALL contain a hits list and the same non-negative `page_count`. For a non-truncated result the materialized raw hit count MUST equal terminal `nreported`. Successful empty output SHALL require exactly terminal `nreported=0`, provider `page_count=0`, and `hits=[]` on the explicit first result request. This change MUST NOT alter `max_hits`, provider ordering, score filtering, or parsed-hit schema.

#### Scenario: Ignore terminal-body hits and retrieve page one explicitly
- **WHEN** a terminal poll payload includes 50 hits but the configured explicit result page contains 100 or 1000 hits
- **THEN** the terminal body supplies only status/count closure, explicit result page 1 supplies the first materialized hits, and later pages follow the same width without a gap or duplicate

#### Scenario: Reject incomplete non-truncated materialization
- **WHEN** explicit result pages drift in `page_count` or their raw-hit total differs from terminal `stats.nreported` below the `max_hits` cap
- **THEN** the provider fails closed as schema drift or partial result and no parsed HMMER artifact can support cutover

#### Scenario: Accept an exact successful empty result
- **WHEN** a terminal SUCCESS reports `nreported=0` and explicit page 1 reports `page_count=0` with `hits=[]`
- **THEN** the provider emits the typed empty result; any other count/page/hits combination fails closed

### Requirement: HMMER-to-UniProt identity-preserving join
The workflow SHALL parse the sealed EBI HMMER `refprot` output with the exact provider schema, derive UniProt accessions with `hmmer_score_filtered_accessions@1` using score strictly greater than `200`, call UniProt only with that exact non-empty accession artifact/set, and derive `target.fasta` plus `hits_len650_700_200.csv` with `aox_sequence_length_join@2`. UniProt `uniprot_primary_sequence_identity@2` SHALL partition the complete requested set exactly and mutually exclusively into strict active sequence records and a typed `Inactive` discriminated union containing only `DELETED` and `MERGED`. An active raw result MUST have exact provider `entryType` `UniProtKB reviewed (Swiss-Prot)` or `UniProtKB unreviewed (TrEMBL)`, deriving `reviewed=true` or `reviewed=false`, respectively. If an explicit raw `reviewed` field exists, it MUST be a boolean equal to the derived value; active `inactiveReason`, an inactive/unknown entry type, or any reviewed/entry-type disagreement SHALL fail closed. Provider metadata MUST expose a non-empty ordered `response_digests` list whose canonical-JSON SHA-256 equals `aggregate_response_digest`; every active/inactive `response_digest` MUST crosslink into that list and every inactive `record_digest` MUST be recomputable from the exact canonical `provider_metadata` object. Provider metadata MUST also expose exact `active_record_count`, `inactive_record_count`, `inactive_deleted_record_count`, and `inactive_merged_record_count` closure. Every inactive record MUST have exactly `requested_accession`, `primary_accession`, `uniprot_identifier`, `entry_type`, `inactive_reason`, `uniparc_id`, `uniprot_release`, `uniprot_release_date`, `retrieved_at`, `response_digest`, `record_digest`, and `provider_metadata`. An inactive member MUST exactly equal one requested primary accession from its producing query. `DELETED` `inactive_reason` MUST be exactly `{inactive_reason_type,deleted_reason}` with a non-empty canonical reason; `MERGED` `inactive_reason` MUST be exactly `{inactive_reason_type,replacement_target_annotations}` with a non-empty unique target list. Each replacement annotation MUST be the exact closed mapping `annotation_type=provider_inactive_replacement`, `source_database=uniprotkb`, `source_accession=<requested accession>`, `target_database=uniprotkb`, `target_accession=<provider target>`, `relationship=merged_into`, `identity_replaced=false`, and `target_followed=false`. Both variants MUST retain UniParc id, release/retrieval identity, response digest, and record digest, MUST contain no sequence or entry audit, and MUST NOT be followed, fetched, replaced, or supplied sequence from a replacement, UniParc, or HMMER. `aox_sequence_length_join@2` SHALL deterministically exclude both inactive variants before applying inclusive length `650..700` to active UniProt sequence bytes. HMMER-provided or model-inferred length/sequence MUST NOT replace UniProt truth. `DEMERGED`, unknown/malformed inactive, active-without-sequence, missing/duplicate/extra identity, a completely empty response, or partition drift SHALL fail closed.

Join metadata MUST expose exactly `input_hit_count`, `uniprot_record_count`, `uniprot_active_record_count`, `uniprot_inactive_record_count`, `uniprot_inactive_deleted_record_count`, `uniprot_inactive_merged_record_count`, `output_hit_count`, `inactive_excluded_count`, `inactive_deleted_excluded_count`, `inactive_merged_excluded_count`, and `length_rejected_count`. These values MUST prove input = all records = active + inactive, inactive = deleted + merged = excluded, each reason count = its excluded count, and active = output + length rejected. Sorted `identity_mappings` MUST use `status=active_sequence` for active members and `status=inactive` for both inactive variants; inactive mappings MUST retain exact requested/primary identity, `identity_replaced=false`, UniParc/digests, and the same closed nested `inactive_reason` without granting target-fetch or sequence authority.

For every cutover-eligible positive that reaches UniProt, `scientific_checks.sequence_join.uniprot_raw_response_artifact_id` MUST identify exactly one artifact in the formal `uniprot_fetch` controlled-operation outputs and in the matching UniProt provider receipt `artifact_ids`; its artifact provenance, operation id, content digest, formal scope, and completed status MUST close over that same operation. The provider receipt `request_digest` MUST equal the same operation's `params_digest`, recomputed from the sealed canonical params. The completed operation outputs and completed provider receipt `artifact_ids` MUST contain the identical exact-three set of distinct artifacts, each exactly once and with roles exactly `uniprot_raw_response`, `uniprot_metadata`, and `uniprot_sequences`. Every member's role, formal scope, origin operation, provider operation, and content digest MUST agree; a request, observation, or error diagnostic artifact MUST NOT be mixed into or substituted for the exact-three science set. The network-free verifier MUST parse the raw artifact and every response body as duplicate-free/non-finite-free strict JSON. The raw envelope MUST be the closed four-field `provider_raw_http_response_set@1` UniProt/fetch envelope and every response MUST be the closed eight-field record whose ordinal, page phase, successful status, canonical base64, byte size, body digest, sanitized headers, and response order are recomputed. Every page MUST carry one identical non-empty `x-uniprot-release` exactly equal to metadata. `x-uniprot-release-date` MUST either be absent from every page while metadata is null, or be present identically on every page and equal metadata; partial or drifting dates SHALL fail closed.

The verifier MUST use the engine provider sanitizer to rebuild an exact bijection between raw results and metadata by requested plus primary identity. Unrelated raw result fields MAY be present, but the complete sanitized result minus sequence MUST equal `provider_metadata` and the complete sanitized result MUST recompute `record_digest`; the observed diagnostic exact-five inactive shape MUST NOT be used as a future raw-field allowlist. Every active raw `sequence.value`, after `strip().upper()`, MUST be non-empty and contain only accepted protein symbols; its non-boolean integer raw length MUST equal the normalized byte length and MUST reproduce metadata `sequence_length` plus `sequence_digest`, after which the existing metadata-to-FASTA join MUST still close. Inactive raw results MUST contain neither `sequence` nor `entryAudit` and MUST reproduce the exact DELETED reason or MERGED replacement annotations with `identity_replaced=false` and `target_followed=false`.

The UniProt call SHALL retain route policy `bio.uniprot_fetch.provider:v1` while binding `provider_config:uniprot:v3`. The complete accession set SHALL be submitted as exactly one SDK call, approval, provider request, and durable controlled operation, with a total operation cap of `100000` accessions. Inside that operation the Host SHALL partition normalized accessions into fixed queries of no more than `100`; `batch_size` SHALL remain the response-page `size` with maximum `100` and MUST NOT change query width. Every query SHALL follow its own `Link: rel=next` chain with an independent `100`-page cap. A remaining next link at the cap SHALL fail non-retryably as `provider_partial_result`. Every next link MUST use HTTPS host `rest.uniprot.org`, implicit or explicit port `443`, exact path `/uniprotkb/search`, and no userinfo or fragment. A malformed or off-origin link SHALL fail as `provider_schema_drift`; the safe error SHALL retain only the link digest and fixed expected endpoint, not the candidate URL.

Before approval, the SDK resource prediction SHALL expose accession count, default `query_batch_size_cap=100`, and `estimated_query_batch_count`. Under the pinned default configuration, the corrected current complete set of `37772` accessions SHALL predict `378` queries. This prediction is transparent planning information, not authorization or an authoritative actual-limit snapshot: the injected Host provider configuration MAY tighten limits and SHALL perform final validation before provider HTTP. The sanitized transcript SHALL bind every request to global page, query-batch index/count, accession start/count/digest, page-in-query, safe headers, status, and response digest; summary pagination SHALL bind total page count, page size, per-query page cap, query count, and query cap. Every response page SHALL be validated only against the exact accession slice/digest of the query that produced it; an identity belonging to another query in the same operation SHALL fail as `provider_identity_mismatch`. Duplicate and exact-order checks SHALL use precomputed sets/frequency maps rather than repeated full-set construction, followed only by deterministic sorting of detected duplicate keys, and operation-cap or duplicate failure SHALL occur before provider HTTP.

#### Scenario: Advance from HMMER to UniProt
- **WHEN** the canonical HMMER score-filter artifact contains one or more accessions
- **THEN** one UniProt controlled operation binds that exact artifact and exact accession set, all internal queries/pages remain under its one approval and transcript, and the sequence join preserves HMMER numeric provenance alongside the exact active/inactive partition, UniProt release, reviewed active status, response/record/sequence digests where applicable, reason-specific annotation/UniParc identity for inactive members, and explicit mapping annotations

#### Scenario: Close raw UniProt bytes through metadata and FASTA
- **WHEN** a cutover-eligible positive reaches UniProt and declares its sequence-join raw-response artifact
- **THEN** its provider request digest equals the sealed operation params digest, the exact-three raw/metadata/sequences artifacts close identically across operation output and provider receipt, every ordered raw page/body/header/release digest is reproduced, each sanitized raw result maps bijectively to metadata, active raw sequence length/digest continues through the metadata-to-FASTA join, and inactive reason/non-follow semantics are reproduced without network access

#### Scenario: Reject UniProt request or exact-three artifact drift
- **WHEN** `request_digest` differs from `params_digest`, an operation/provider set misses or adds an artifact, repeats a member, changes a role/op/scope/content digest, or includes a request/observation/error diagnostic
- **THEN** offline verification fails closed even if the raw body, metadata, FASTA, and outer bundle digests are otherwise self-consistent

#### Scenario: Derive reviewed status from exact active entry type
- **WHEN** an active raw result uses either accepted UniProtKB entry type and optionally carries an explicit boolean `reviewed`
- **THEN** normalization derives the matching reviewed value from `entryType` and accepts the explicit field only when it is the same boolean

#### Scenario: Reject active entry-type or reviewed drift
- **WHEN** an active result uses another entry type, carries `inactiveReason`, has a non-boolean explicit reviewed field, or disagrees with the reviewed value derived from its accepted entry type
- **THEN** provider normalization fails closed without adding the record to the active or inactive partition

#### Scenario: Reject re-sealed raw or metadata drift
- **WHEN** raw and metadata artifacts are both re-sealed after changing response order/body, release headers, an active sequence/length, inactive sequence/audit, DELETED/MERGED semantics, operation/provenance/provider-receipt identity, or sanitized provider metadata
- **THEN** offline verification fails closed even if outer artifact and bundle digests are internally consistent

#### Scenario: Exclude a valid deleted identity before length filtering
- **WHEN** one requested accession returns an exact `Inactive`/`DELETED` record with canonical reason, UniParc id, release and digests while all other requested identities are valid active records
- **THEN** the partition is complete, the inactive identity contributes no sequence and is excluded before the active length filter, and join metadata makes input=active+inactive and active=output+length-rejected recomputable with a sorted inactive mapping

#### Scenario: Preserve but do not follow a valid merged identity
- **WHEN** one requested accession returns an exact `Inactive`/`MERGED` record with non-empty unique replacement-target annotations, UniParc id, release and digests while all other requested identities are valid active records
- **THEN** the requested accession remains the identity with `identity_replaced=false`, every annotation uses the exact provider-inactive-replacement/uniprotkb/merged-into shape with `target_followed=false`, the replacement targets remain annotations only, no target is fetched or used as sequence, the inactive identity is excluded before length filtering, and reason-specific counts plus sorted mapping make the partition recomputable

#### Scenario: Reject an unknown or incomplete inactive partition
- **WHEN** an inactive record is `DEMERGED` or has an unknown reason type, follows/fetches/replaces another accession, contains sequence/audit, lacks its reason-specific annotation/UniParc/release/digest, has empty or duplicate MERGED targets, or any requested identity is absent
- **THEN** provider normalization or `aox_sequence_length_join@2` fails closed without shrinking the requested set or consulting UniParc/HMMER for replacement sequence

#### Scenario: Estimate the corrected current accession set before approval
- **WHEN** the exact complete score-filter artifact contains `37772` accessions under the pinned default query cap of `100`
- **THEN** the one controlled operation predicts `accession_count=37772`, `query_batch_size_cap=100`, and `estimated_query_batch_count=378` before provider I/O; it does not create 378 operations or approvals, and Host validation remains authoritative if injected limits are tighter

#### Scenario: Keep page size separate from query width
- **WHEN** the caller sets any allowed `batch_size` and one or more accession queries have `Link: rel=next`
- **THEN** every query still contains at most 100 accessions, `batch_size` controls only response-page size, page numbering and the 100-page bound restart per query, and every page remains transcript-bound to that query

#### Scenario: Reject an unsafe pagination link
- **WHEN** UniProt supplies a malformed next link or one with another scheme, host, non-443 port, path, userinfo, or fragment
- **THEN** pagination stops with `provider_schema_drift`, no request is sent to that link, and public diagnostics contain only its digest plus the fixed expected endpoint

#### Scenario: Reject a cross-query identity swap
- **WHEN** a UniProt response page contains an identity requested by the operation but not by the exact query slice that produced that page
- **THEN** response validation fails as `provider_identity_mismatch`, preserves the page/query transcript coordinates, and does not move the record to another query or accept operation-wide membership

#### Scenario: Reject an oversized or duplicate accession set before HTTP
- **WHEN** the exact operation contains more than `100000` accessions or contains a duplicate accession
- **THEN** request validation fails before HTTP with a deterministic bounded diagnostic, without partial provider I/O, hidden deduplication, operation splitting, or replacement approval

#### Scenario: Stop before UniProt on upstream empty
- **WHEN** the canonical HMMER score-filter result is header-only
- **THEN** no formal UniProt operation or provider I/O occurs, and `provider_upstream_empty_receipt@1` binds the trigger artifact, derivation operation, stable reason, and `provider_io_performed=false` without fabricated invocation/request/response digests

### Requirement: Sealed provider artifacts and safe projection
Raw or parsed provider outputs used by science SHALL be registered as sealed artifacts with content digests and provenance. Public projections MUST hide credentials, Host paths, remote paths, private headers, and unlicensed full text.

#### Scenario: Register provider evidence
- **WHEN** a provider response contributes to filtering, scoring, or reporting
- **THEN** its safe transcript, parsed data, request summary, release/version metadata, retrieval time, and content digest can be traced from the final evidence bundle

#### Scenario: Keep failure diagnostics outside normalized science
- **WHEN** a failed sandbox provider operation registers its request/observation/error diagnostic trio
- **THEN** those artifacts preserve terminal failure evidence but do not count as provider success, parsed scientific output, or any of the 17 normalized AOX deliverables

#### Scenario: Project evidence to UI
- **WHEN** the workspace or event stream exposes provider evidence
- **THEN** it shows citation/status/provenance summaries without exposing secrets or storage locations
