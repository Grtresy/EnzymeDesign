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
- **THEN** the candidate records primary accession, reviewed status, UniProt release, retrieval time, sequence digest, mapping provenance, and response digest

#### Scenario: Mapping changes sequence identity
- **WHEN** a mapped UniProt sequence differs from the sequence already bound to another source identity
- **THEN** both identities and digests remain visible and the system requires an explicit selection rather than overwriting one with the other

### Requirement: HMMER-to-UniProt identity-preserving join
The workflow SHALL parse the sealed EBI HMMER `refprot` output with the exact provider schema, derive UniProt accessions with `hmmer_score_filtered_accessions@1` using score strictly greater than `200`, call UniProt only with that exact non-empty accession artifact/set, and derive `target.fasta` plus `hits_len650_700_200.csv` with `aox_sequence_length_join@1` using UniProt sequence identity and inclusive length `650..700`. HMMER-provided or model-inferred length/sequence MUST NOT replace UniProt truth.

#### Scenario: Advance from HMMER to UniProt
- **WHEN** the canonical HMMER score-filter artifact contains one or more accessions
- **THEN** the UniProt operation binds that exact artifact and exact accession set, and the sequence join preserves HMMER numeric provenance alongside UniProt release, reviewed status, response digest, sequence digest, and explicit mapping annotations

#### Scenario: Stop before UniProt on upstream empty
- **WHEN** the canonical HMMER score-filter result is header-only
- **THEN** no formal UniProt operation or provider I/O occurs, and `provider_upstream_empty_receipt@1` binds the trigger artifact, derivation operation, stable reason, and `provider_io_performed=false` without fabricated invocation/request/response digests

### Requirement: Sealed provider artifacts and safe projection
Raw or parsed provider outputs used by science SHALL be registered as sealed artifacts with content digests and provenance. Public projections MUST hide credentials, Host paths, remote paths, private headers, and unlicensed full text.

#### Scenario: Register provider evidence
- **WHEN** a provider response contributes to filtering, scoring, or reporting
- **THEN** its safe transcript, parsed data, request summary, release/version metadata, retrieval time, and content digest can be traced from the final evidence bundle

#### Scenario: Project evidence to UI
- **WHEN** the workspace or event stream exposes provider evidence
- **THEN** it shows citation/status/provenance summaries without exposing secrets or storage locations
