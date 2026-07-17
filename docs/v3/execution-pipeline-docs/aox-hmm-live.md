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
| motif rule | `aox_motif_rule_score@1` | `sha256:7f79044132e0f45afa5cb47776ad9c3bc10cea25c7c6de1007e50325ea49a086` | `sha256:0eb1c4a28160389b805d3b9a28b9d664cad532082a08df206e12ee5d09c9d0f7` |
| real-sequence similarity | `aox_global_sequence_identity@1` | `sha256:4e8b8ec490808f6c32f25868c2f2321db1fa55e7476b7a9d6bd58574a0b9d5ad` | `sha256:786492107e48ddeefee633c7282324511fc09a365d869c381855cf335c364949` |
| HMM reference selection | `aox_hmm_reference_set_selection@1` | `sha256:34659d9f384af0b9d63f2d7d66f21927cd438ad222458169114835ec368ebbbf` | `sha256:8abb77c737fcf29ee659e0ae0ef7204ecc8f0f49843eb4a0098a4b5edc2666ba` |
| coordinate reference selection | `aox_reference_selection@1` | `sha256:1923a047f4bf0ce5b70f9c1bfa16a2e6453379abd1850d7bf7654a4721bb0f49` | `sha256:8abb77c737fcf29ee659e0ae0ef7204ecc8f0f49843eb4a0098a4b5edc2666ba` |
| scoring input assembly | `aox_scoring_input_assembly@1` | `sha256:42e9926ac2f9a8b88d3117838f919d8a966171a65265854dabb6105ef4255e85` | `sha256:8abb77c737fcf29ee659e0ae0ef7204ecc8f0f49843eb4a0098a4b5edc2666ba` |
| pre-UniProt HMMER score filter | `hmmer_score_filtered_accessions@1` | `sha256:ed939fa871a6410cfbaae9c5dad0fa96b53c7b0e21f8351daec17d31b62278ee` | `sha256:a08e271fe92a2a1a3be13c09cf913af7639925c7d2ab8c2203a46d0e271ffc83` |
| UniProt sequence/length join | `aox_sequence_length_join@1` | `sha256:3e26e8925da62fe50dc9f65c61fb5848af08519b2688538b07a6f8bed6c7663a` | `sha256:a0a6cf638c03b08e7baba2c2f0c273ccd73d976af205ed05676aad63c5a49948` |

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

The formal scientific closure always reaches `bio.ncbi_fetch_proteins`,
`bio_tools.mafft`, `bio_tools.hmmbuild`, and
`bio.hmmer_search(database="refprot")`. It reaches `bio.uniprot_fetch` only
when the canonical HMMER score filter yields a non-empty accession set,
`bio_tools.hmmalign` only when the post-UniProt target FASTA is non-empty, and
`bio_tools.cdhit` only when at least one target passes the motif rule. The
executor still uses `hpc.workspace`, `hpc.stage_artifact`,
`hpc.fetch_outputs`, and `artifacts.register` wherever the reached operation
requires those Host-supervised mechanics.

This is a branch-derived evidence closure, not a unique execution order and not
permission to omit a reached dependency. The offline verifier derives the
branch from sealed raw/parsed and calculated artifacts, then requires the exact
formal operation set for that branch and rejects extra or hidden failed
operations. The agent may batch, inspect, retry within the bounded policy, or
stop at a proven empty prerequisite without asking the harness to invent an
alternate route.

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
   `hmmer_score_filtered_accessions.csv`;
3. only a non-empty exact artifact/accession set may be bound as the
   `bio.uniprot_fetch` source-hit input;
4. `aox_sequence_length_join@1` joins by preserved accession identity, takes
   sequence length and bytes only from the sealed UniProt response, applies the
   inclusive `650..700` filter, and emits `target.fasta` plus
   `hits_len650_700_200.csv`.

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

Likewise, every similarity value and cluster id must come from declared tool
output or a versioned, auditable calculation. Do not emit constant `0.91` edges
or a constant cluster id.

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
  `aox_sequence_length_join@1`, including the UniProt-derived sequence
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
  fields, HMMER score-filter drift, a reached but unbound UniProt accession,
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
