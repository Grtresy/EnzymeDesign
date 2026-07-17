## ADDED Requirements

### Requirement: Required PubMed literature evidence
The AOX/HMM cutover workflow SHALL require at least one real PubMed record supporting the scientific context. Each accepted record MUST carry a PMID, provider identity, title, source locator, retrieval time, response digest, and available bibliographic fields; a DOI SHALL be recorded when PubMed supplies one and MUST NOT be invented when absent.

#### Scenario: Required literature quorum succeeds
- **WHEN** PubMed returns one or more schema-valid records and the report links its scientific claims to their source refs
- **THEN** the required literature quorum is `complete` and the sealed evidence contains only safe citation metadata, digests, and licensed content

#### Scenario: Required literature is unavailable
- **WHEN** PubMed fails, returns a malformed response, or returns no evidence for the bounded AOX query set
- **THEN** the workflow records the provider failure or empty result and cannot become cutover eligible

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
The workflow SHALL fetch the fixed 13 reference accessions from NCBI and SHALL use UniProt accession identity for EBI HMMER `refprot` candidate hits. Cross-database mappings MUST be explicit annotations and MUST NOT silently replace sequence bytes or identifiers.

#### Scenario: Seal NCBI reference sequences
- **WHEN** NCBI returns the fixed reference set
- **THEN** the artifact records requested and resolved accessions, sequence digests, retrieval identity, provider request ids, missing/duplicate mappings, and a sealed aggregate FASTA digest

#### Scenario: Enrich a UniProt candidate
- **WHEN** an EBI HMMER hit resolves to a UniProt record
- **THEN** the candidate records primary accession, reviewed status, UniProt release, retrieval time, sequence digest, mapping provenance, and response digest

#### Scenario: Mapping changes sequence identity
- **WHEN** a mapped UniProt sequence differs from the sequence already bound to another source identity
- **THEN** both identities and digests remain visible and the system requires an explicit selection rather than overwriting one with the other

### Requirement: Sealed provider artifacts and safe projection
Raw or parsed provider outputs used by science SHALL be registered as sealed artifacts with content digests and provenance. Public projections MUST hide credentials, Host paths, remote paths, private headers, and unlicensed full text.

#### Scenario: Register provider evidence
- **WHEN** a provider response contributes to filtering, scoring, or reporting
- **THEN** its safe transcript, parsed data, request summary, release/version metadata, retrieval time, and content digest can be traced from the final evidence bundle

#### Scenario: Project evidence to UI
- **WHEN** the workspace or event stream exposes provider evidence
- **THEN** it shows citation/status/provenance summaries without exposing secrets or storage locations
