## ADDED Requirements

### Requirement: Immutable AOX motif scoring contract
The system SHALL expose the scientific calculation as `aox_motif_rule_score@1` with an immutable contract digest covering the reference accession, coordinate convention, residue rules, weights, threshold, output schema, and implementation source digest. It MUST NOT describe this heuristic as an experimental activity prediction.

#### Scenario: Resolve the scoring identity
- **WHEN** an AOX/HMM workflow binds `aox_motif_rule_score@1`
- **THEN** the run records the exact contract version, contract digest, implementation digest, reference accession `AAB57849.1`, and threshold `33.6`

#### Scenario: Reject scoring drift
- **WHEN** the bound contract, implementation source, or expected digest differs from the workflow manifest
- **THEN** the system fails before producing candidate artifacts with `scientific_prerequisite_missing` or a more specific digest-drift error

### Requirement: Canonical HMMER AFA input boundary
Aligned FASTA SHALL bind `hmmer_afa_alignment_canonicalization@1`. The raw `input_digest` MUST be SHA-256 over the exact pre-normalization bytes. The parser MUST split physical segments only on LF and remove exactly one CR only from a segment actually terminated by LF; a lone trailing CR, repeated CR, or another bare CR MUST fail closed. `>` MUST occur at raw column zero to start a header. Only an exactly empty physical line MAY be ignored; a non-empty whitespace line is not empty. Before strip, uppercase, or any Unicode normalization, each non-empty raw sequence line MUST match ASCII `^[A-Za-z.-]+$`. After raw validation only, the parser SHALL uppercase ASCII residues and map `.` to the canonical alignment gap `-`. The canonical `alignment_digest` SHALL cover the sorted normalized records and alignment width, so legal case-only and `.`/`-` variants retain distinct raw digests but share canonical aligned-sequence/alignment digests.

#### Scenario: Canonicalize legal HMMER insert gaps
- **WHEN** two valid AFA inputs differ only by ASCII residue case or use `.` versus `-` for gap columns
- **THEN** their raw input digests remain distinct while their canonical aligned sequences, alignment digest, coordinate observations, and score rows are equal

#### Scenario: Reject text normalization ambiguity
- **WHEN** a header is indented, a sequence line contains any leading/trailing/internal whitespace, a CR is lone/repeated/not LF-terminating, or a sequence contains `ß`, `ſ`, non-ASCII, or another character outside the raw ASCII grammar
- **THEN** parsing fails before strip/uppercase/Unicode expansion and no cutover-eligible scoring output is produced

#### Scenario: Exercise a real AFA without adopting it
- **WHEN** the final parser/scorer is run read-only on the observed 12,273,402-byte, 2,562-record, width-4,700 HMMER 3.4 AFA
- **THEN** it reproduces raw digest `sha256:d72e36bc5c0431d8f3806eb4d0d0cadb51e7d3825c873610d8e4c0098eccf7a6`, canonical alignment digest `sha256:2df12971eae2d83c390f22e689e04e493539cf6be2d79599f33823f0f52df836`, 517 total passes including AAB and 516 non-reference passes, while the ordinary diagnostic remains non-sealed and non-cutover

### Requirement: Reference-coordinate motif calculation
The scorer SHALL map one-based ungapped residue coordinates from `AAB57849.1` onto the declared multiple-sequence alignment and calculate exactly these rules: positions 13/15/18 require `G` for 5 points each; position 98 requires `F|W|Y` for 5; positions 417 and 566 require `F|W|Y` for 2 each; position 567 requires `H` for 5; position 616 requires `H|N|P` for 5; and each non-gap residue at positions 660 through 663 contributes `-0.1`. The canonical calculation MUST use exact integer tenths (`50`, `20`, and `-1`) and compare against the integer threshold `336`; the decimal `33.6` is only a presentation value. A sequence passes only when its exact score is at least `336` tenths.

#### Scenario: Score a valid aligned sequence
- **WHEN** an alignment contains exactly one resolvable `AAB57849.1` reference and a target sequence with observable residues at the rule columns
- **THEN** the scorer emits the sum of the declared weights and the per-rule observed residue without substituting HMM scores or model-generated values

#### Scenario: Score the exact pass boundary
- **WHEN** a sequence satisfies all positive rules and has a non-gap residue at each of positions 660 through 663
- **THEN** its exact score is `336` tenths, it is rendered as `33.6`, and `passes_motif_rule` is true without binary floating-point ambiguity

#### Scenario: Fail on ambiguous scientific coordinates
- **WHEN** the reference is missing, duplicated ambiguously, truncated before a required coordinate, alignment widths differ, or a rule column cannot be resolved
- **THEN** the scorer returns a structured scientific prerequisite failure and registers no cutover-eligible scored candidate output

### Requirement: Corrected scoring output schema
The canonical scored output SHALL use `motif_rule_score` and `passes_motif_rule`, include every per-rule residue observation, and carry the scoring contract id/digest and reference identity. The product contract MUST NOT use `activity_score`, `seq_score`, or `pass_rule` as canonical scientific field names.

#### Scenario: Export scored candidates
- **WHEN** scoring succeeds for the current aligned reference-plus-hit dataset
- **THEN** `scored_ref_plus_hits.csv` contains the corrected canonical fields and enough provenance to reproduce every row

#### Scenario: Reject legacy-only output
- **WHEN** an output contains only legacy `activity_score`, `seq_score`, or `pass_rule` fields
- **THEN** cutover validation rejects it rather than interpreting it as `aox_motif_rule_score@1`

### Requirement: Exact motif candidate calculation
The sandbox SDK SHALL expose `aox_motif_candidate_filter@1` as a dependency-free
typed calculation over canonical `aox_motif_rule_score@1` rows and the exact target
FASTA identity. It SHALL accept only `passes_motif_rule` and
`motif_rule_score_tenths`, verify the scorer contract/implementation, sequence,
reference, alignment and input digests, exclude the coordinate reference, and
serialize the selected target sequences in canonical lexical FASTA order. Its
closed result and metadata SHALL publish the candidate count, membership digest,
output digest, calculation contract digest, and calculation implementation digest.
No agent-local field alias, source snapshot, empty file, or prose assertion MAY
substitute for the installed calculation or its canonical serializer.

#### Scenario: Select the r65-shaped candidate set
- **WHEN** canonical scorer rows contain the coordinate reference plus 2,561 target records and exactly 516 target records have `passes_motif_rule=true`
- **THEN** the exact candidate calculation emits 516 target records and a non-zero canonical FASTA; a filter that reads legacy or invented field names fails closed rather than returning healthy empty

#### Scenario: Materialize a typed healthy empty result
- **WHEN** canonical scorer rows validly contain no passing target
- **THEN** the calculation emits an exact zero-candidate result and canonical zero-record FASTA with a source-bound typed empty reason, rather than inferring emptiness from file size or a missing field

### Requirement: Exact conditional-empty calculations
Every operation-omitting AOX branch SHALL use an installed typed calculation with a
closed input/result schema, canonical serializer, contract digest, and real
implementation digest. `aox_upstream_empty_materialization@1`,
`aox_reference_only_scoring_alignment@1`, and
`aox_empty_membership@1` MAY activate only from their exact upstream typed zero
receipt and SHALL bind every emitted empty/header-only deliverable. A sealed source
snapshot proves only sandbox source identity and MUST NOT be recorded as any of
these calculation implementations.

#### Scenario: Reject an arbitrary source implementation substitute
- **WHEN** a sandbox source digest is supplied without the installed calculation result and serializer receipt
- **THEN** qualification and finalization reject the branch even if all empty files and metadata are self-consistent

### Requirement: Reference golden compatibility
The implementation SHALL be tested against immutable, minimal golden inputs derived from the user-authorized reference notebook and runner, while keeping all reference outputs outside live input roots. Golden expectations SHALL cover exact scores, pass decisions, rule residues, ordering, and failure cases.

#### Scenario: Run the scoring golden suite
- **WHEN** the non-live golden tests execute
- **THEN** the independent product implementation matches the recorded reference expectations and verifies the golden input digest

#### Scenario: Run a blank-world live workflow
- **WHEN** a live AOX/HMM run starts from clean roots
- **THEN** no notebook file, historical reference FASTA/HMM/CSV, or golden expected output is materialized as a scientific input or accepted as live evidence

### Requirement: Auditable similarity and clustering
Candidate cluster ids and graph similarities SHALL come from declared CD-HIT output and `aox_global_sequence_identity@1` over real candidate sequences. For sequence lengths `m,n`, with `R=max(m,n)+1`, every dynamic-programming state tuple `(score_half_units, exact_matches, aligned_residue_pairs)` SHALL be represented exactly as `score_half_units * R^2 + exact_matches * R + aligned_residue_pairs`. Because both counts are in `[0,R)`, integer comparison MUST preserve the former tuple lexicographic priority without changing the published scientific result; reference Gotoh state order and the gap extension-versus-opening tie remain tie provenance rather than an output-path promise. Candidate FASTA MUST use LF-only segmentation, raw-column-zero headers, exact empty-line semantics, and raw ASCII validation before uppercase; whitespace, gap/insert-gap/stop residues, CR drift, Unicode expansion, and residues outside the embedded BLOSUM62 alphabet MUST fail closed.

The frozen backend SHALL be `biopython_trace_guarded_numpy_gotoh@1`, Biopython `1.87`, NumPy `2.4.4`, and `Gotoh global alignment algorithm`. Packed values MAY pass through IEEE-754 binary64 only after a strict per-pair absolute bound proves the value is below `2^53`; every returned score MUST be finite, integral within `0.000001`, and inside the proven bound. The first optimal coordinate trace MUST be inspected. An adjacent horizontal/vertical gap-state switch SHALL activate `numpy_three_state_gap_switch_correction@1`, an exact NumPy `int64` row-vectorized three-state recurrence. That correction is part of the calculation contract, not a fallback. Import, exact-version, algorithm, binary64, score, trace, or correction failure MUST fail closed, and the runtime MUST NOT retry with pure Python, another package, another package version, or an alternate backend. Reference recurrence state order SHALL be treated only as tie provenance for the published score/count tuple; this calculation SHALL NOT promise or publish coordinates or a selected alignment path. Any future coordinates/path output MUST use a new calculation id and an explicit trace construction/canonicalization/serialization contract.

Pair indexes MUST be lexical. Fewer than `128` pairs SHALL execute serially; `128` or more SHALL be parallel-eligible. Worker count SHALL be the minimum of pair count, hard maximum `16`, available CPU affinity (or `cpu_count` only when affinity is unavailable), and every available cgroup v2/v1 CPU quota divided by period and rounded up. An available but unreadable, incomplete, or malformed cgroup constraint MUST fail closed. Worker count `1` SHALL select serial execution before work begins; only a larger count SHALL use ordered process mapping with `chunksize=64`. Ordered mapping and canonical filtering MUST preserve byte-identical edge order regardless of worker completion. Pool creation, worker, serialization, or result failure after the parallel branch begins MUST return `scientific_prerequisite_missing:similarity_parallel_execution_failed`; there MUST be no hidden serial retry or fallback. Constant cluster ids, constant edge weights, synthetic sequences, copied HMM/motif scores, or execution-identity drift SHALL be rejected.

The independent reference-validation environment SHALL be identified as NumPy `2.4.6`, distinct from the cutover runtime pin NumPy `2.4.4`. Final diagnostic qualification MUST bind current implementation/calculation digests, exact inputs, package/backend/correction identities, effective cgroup/worker facts, counts, timings, and canonical output digests for two independent exact-cutover-`2.4.4` full-set runs. Their raw outputs MUST be byte-identical; after requiring and normalizing only calculation/implementation pin fields and pin-induced manifest artifact-digest closure, both MUST be byte-identical to the frozen pure-v3 result with all non-pin fields equal. If production exposes no correction-activation counter and authoritative wrapping is forbidden, the receipt MUST record typed `unavailable` plus the reason rather than fabricate zero. This evidence MUST NOT be described as a direct full-set `2.4.6`/`2.4.4` patch A/B or make `2.4.6` an allowed runtime. The patch difference MUST NOT authorize runtime fallback. Historical pure-v3, temporary Podman calibration, and final ordinary `/tmp` receipts SHALL remain explicitly non-cutover and MUST NOT satisfy a live positive attempt.

#### Scenario: Build a non-empty candidate graph
- **WHEN** the motif filter yields at least two real candidate sequences
- **THEN** every node and edge links to sequence digests, calculation/tool identity, parameters, and actual parsed outputs

#### Scenario: Build an empty candidate graph
- **WHEN** the real motif filter yields no candidates
- **THEN** the system emits schema-valid empty node/edge artifacts plus an explicit empty-result explanation and no fabricated rows

#### Scenario: Preserve mixed-radix tuple equivalence
- **WHEN** the pinned backend scores any legal residue or gap transition within the proven binary64 exact-integer bound
- **THEN** its decoded score, exact-match count, aligned-residue count, terminal choice, and serialized identity are identical to the declared three-integer tuple recurrence

#### Scenario: Correct an opposite gap-state switch
- **WHEN** the first optimal Biopython trace contains an adjacent horizontal/vertical gap-state switch
- **THEN** the versioned exact NumPy three-state correction supplies the pair result, and correction failure emits a typed prerequisite error without alternate-backend fallback

#### Scenario: Reject backend drift
- **WHEN** Biopython/NumPy import, exact versions, algorithm, binary64 representation, numeric bounds, integral score, or trace validation differs from the frozen contract
- **THEN** the calculation fails closed before emitting graph rows and does not select another version or backend

#### Scenario: Preserve canonical order in parallel
- **WHEN** at least 128 lexical candidate pairs yield a worker count greater than one and are evaluated with the bounded process pool
- **THEN** ordered mapping produces the same canonical node/edge/manifest bytes as serial calculation for the same inputs and identities

#### Scenario: Select serial before execution on one available worker
- **WHEN** at least 128 pairs are present but the cgroup/affinity-capped worker calculation yields exactly one
- **THEN** the calculation selects the serial loop before execution and does not create a process pool or describe that choice as a parallel fallback

#### Scenario: Honor a fractional cgroup quota
- **WHEN** an available cgroup v2 or v1 quota divided by period is fractional and is tighter than affinity and the hard maximum
- **THEN** its ceiling participates in the worker-count minimum, while malformed or unreadable available limits fail closed

#### Scenario: Fail closed on parallel execution failure
- **WHEN** process-pool creation, serialization, a worker, or result collection fails after the parallel branch is selected
- **THEN** the calculation returns `scientific_prerequisite_missing:similarity_parallel_execution_failed` without silently retrying serially or emitting a partial graph

#### Scenario: Qualify the final current-backend diagnostic
- **WHEN** final r26 similarity diagnostic evidence is proposed for knowledge repinning
- **THEN** receipt `sha256:ace8baa8bfa070a621186d7b3db3acddcdf39abe26070e72270fc727b0017b5e` proves two independent exact-cutover-NumPy-`2.4.4` raw outputs are identical and normalize only pin-induced fields to the frozen pure-v3 bytes, while remaining explicitly non-cutover and making no direct full-set patch-A/B claim
