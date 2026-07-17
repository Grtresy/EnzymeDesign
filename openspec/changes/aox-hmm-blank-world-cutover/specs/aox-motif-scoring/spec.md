## ADDED Requirements

### Requirement: Immutable AOX motif scoring contract
The system SHALL expose the scientific calculation as `aox_motif_rule_score@1` with an immutable contract digest covering the reference accession, coordinate convention, residue rules, weights, threshold, output schema, and implementation source digest. It MUST NOT describe this heuristic as an experimental activity prediction.

#### Scenario: Resolve the scoring identity
- **WHEN** an AOX/HMM workflow binds `aox_motif_rule_score@1`
- **THEN** the run records the exact contract version, contract digest, implementation digest, reference accession `AAB57849.1`, and threshold `33.6`

#### Scenario: Reject scoring drift
- **WHEN** the bound contract, implementation source, or expected digest differs from the workflow manifest
- **THEN** the system fails before producing candidate artifacts with `scientific_prerequisite_missing` or a more specific digest-drift error

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

### Requirement: Reference golden compatibility
The implementation SHALL be tested against immutable, minimal golden inputs derived from the user-authorized reference notebook and runner, while keeping all reference outputs outside live input roots. Golden expectations SHALL cover exact scores, pass decisions, rule residues, ordering, and failure cases.

#### Scenario: Run the scoring golden suite
- **WHEN** the non-live golden tests execute
- **THEN** the independent product implementation matches the recorded reference expectations and verifies the golden input digest

#### Scenario: Run a blank-world live workflow
- **WHEN** a live AOX/HMM run starts from clean roots
- **THEN** no notebook file, historical reference FASTA/HMM/CSV, or golden expected output is materialized as a scientific input or accepted as live evidence

### Requirement: Auditable similarity and clustering
Candidate cluster ids and graph similarities SHALL come from declared CD-HIT output and a versioned similarity calculation over real candidate sequences. Constant cluster ids, constant edge weights, synthetic sequences, and copied HMM/motif scores SHALL be rejected.

#### Scenario: Build a non-empty candidate graph
- **WHEN** the motif filter yields at least two real candidate sequences
- **THEN** every node and edge links to sequence digests, calculation/tool identity, parameters, and actual parsed outputs

#### Scenario: Build an empty candidate graph
- **WHEN** the real motif filter yields no candidates
- **THEN** the system emits schema-valid empty node/edge artifacts plus an explicit empty-result explanation and no fabricated rows
