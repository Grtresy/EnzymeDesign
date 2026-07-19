# AOX real-sequence similarity and graph contract v1

`openzyme_pipeline.aox_similarity` owns the exact-version scientific-backend
`aox_global_sequence_identity@1` calculation and the canonical AOX candidate
graph schemas. It is a pure scientific calculation and verifier inside the
sandbox SDK; it does not own task, approval, operation, artifact, or report
state. Its installed Biopython/NumPy runtime is part of the calculation
boundary; “pure calculation” means no provider or network I/O, not
dependency-free execution.

This contract closes three identities without conflating them:

1. candidate FASTA sequence ids, normalized residue bytes, lengths, and
   SHA-256 digests;
2. the exact parsed `cdhit_cluster_membership@1` rows and membership artifact
   digest;
3. pairwise global-alignment identity calculated from the candidate sequence
   bytes.

CD-HIT `identity_to_representative` remains an observed CD-HIT output. It is
not replaced by, copied into, or assumed equal to the global-alignment
identity. The latter is not an HMM score, motif score, experimental activity
score, or model-generated value.

## Calculation identity

The immutable calculation settings are:

- mode: global affine-gap protein alignment;
- substitution matrix: embedded standard BLOSUM62, whose complete integer
  matrix and matrix digest are covered by the calculation digest;
- numeric unit: integer half-score;
- gap open: `-20` half-score units (`-10.0` display units);
- gap extension: `-1` half-score unit (`-0.5` display units);
- identity numerator: exact residue matches in residue-residue columns;
- identity denominator: all residue-residue columns, excluding gap columns;
- serialized identity: integer parts per million, floored, with a fixed
  six-decimal presentation;
- default graph threshold: `850000` ppm (`0.850000`);
- deterministic optimal-alignment tie break: higher alignment score, then more
  exact matches, then more aligned residue pairs; remaining ties use the
  declared state order and prefer extending an existing gap over an equal
  score gap opening.

The current implementation preserves that three-integer lexical state. For
source/target lengths `m,n`, let `R=max(m,n)+1`. Every state
`(score_half_units, exact_matches, aligned_residue_pairs)` is encoded exactly as

```text
score_half_units * R^2 + exact_matches * R + aligned_residue_pairs
```

Both counts are in `[0,R)`, so integer comparison is mathematically identical
to tuple lexicographic comparison: score first, then matches, then aligned
residue pairs. A residue-residue transition adds
`BLOSUM62_half_score * R^2`, adds `R` only for an exact match, and always adds
`1` for the aligned-residue denominator. Gap transitions change only the score
component. The versioned reference recurrence defines the three Gotoh states,
terminal state order, and `extension >= opening` tie as tuple-result
provenance. Final `divmod` operations recover the three original integers
exactly.

The frozen backend is
`biopython_trace_guarded_numpy_gotoh@1`: Biopython `1.87`
`Bio.Align.PairwiseAligner.score+align()[0].coordinates`, configured to report
`Gotoh global alignment algorithm`, with NumPy `2.4.4`. Packed values travel
as IEEE-754 binary64 only after a per-pair absolute bound proves every reachable
integer is strictly below `2^53`; the backend score must be finite, integral
within `0.000001`, and within that proven bound. Runtime import, exact package
versions, binary64 shape, fixed score probes, algorithm selection, score and
trace agreement, and trace shape are all checked fail closed.

The first optimal traceback is inspected for an adjacent horizontal/vertical
gap-state switch. If one is present, the versioned
`numpy_three_state_gap_switch_correction@1` recomputes that pair with an exact
NumPy `int64`, row-vectorized, three-state recurrence. This correction is a
declared part of the calculation, not an alternate backend or fallback. An
unexpected correction-execution exception returns
`scientific_prerequisite_missing:similarity_gap_switch_correction_failed`;
already typed prerequisite drift retains its typed fail-closed error.
Missing/wrong-version backend, algorithm/numeric/trace drift, or any other
backend failure likewise fails closed; there is no pure-Python, other-package,
other-version, or serial scientific fallback.

The declared reference-recurrence state order is tie provenance for the score,
match-count, and aligned-residue-count result only. Neither this calculation
nor its graph schemas promise or publish an alignment coordinate sequence or
path. The inspected Biopython coordinates are an internal guard, not an output
contract. If a future workflow needs coordinates or a chosen path, it must
introduce a new calculation id and an explicit trace construction,
canonicalization, serialization, and verification contract; it cannot infer a
path guarantee from `aox_global_sequence_identity@1`.

Callers bind all of:

- `CALCULATION_ID`;
- `CALCULATION_DIGEST`;
- `IMPLEMENTATION_DIGEST`.

`calculation_payload()` is the canonical digest payload. Workflow manifests
must pin the values, and `build_similarity_graph()` or
`validate_graph_artifacts()` must receive the expected values at the
fail-closed boundary. A mismatch fails before graph rows are returned.

Current frozen identities are:

- implementation digest:
  `sha256:300ea35bff801782b6bde96d12f206881a6a5aac26a96708ae6756c800aab9b5`;
- calculation digest:
  `sha256:12f98c34460aa3bc59b84c5553771b0bbfb25354febd6558ec381535a0e8286d`.

The calculation digest covers the packed-state identity
`exact_mixed_radix_score_matches_aligned_residues_in_binary64_integer`, the
backend/correction identities and exact versions, lexical pair ordering,
cgroup-aware bounded execution constants below, and the scientific alignment
settings.

The independent reference-validation environment used NumPy `2.4.6`; the
cutover runtime is pinned to NumPy `2.4.4`. That patch difference is explicit:
the environments are not presumed identical, and the runtime MUST NOT switch
between them. Final diagnostic qualification uses two independent exact
cutover-`2.4.4` full-set runs plus pin-only-normalized equality to the frozen
pure-v3 output. It does not claim a direct full-set patch-version A/B or add
reference `2.4.6` to the runtime allowlist; an unavailable exact cutover pin
fails closed.

## Canonical inputs

`parse_candidate_fasta()` accepts gap-free protein FASTA. Physical input is
split only on LF; exactly one CR is removed only when it immediately precedes
the LF terminating that segment. A trailing lone CR, repeated CR, or another
bare CR is rejected. A header marker `>` is recognized only at raw column 0;
leading whitespace cannot be stripped into a header. Explicit empty physical
lines are ignored, but a non-empty sequence line containing leading, trailing,
or internal whitespace is rejected.

Identifiers must be unique ASCII ids. Every sequence line is checked as raw
ASCII before uppercase normalization, and normalized residues must belong to
the embedded BLOSUM62 alphabet without gap `-`, insert gap `.`, or stop `*`.
This prevents non-ASCII characters such as `ß`/`ſ` from becoming valid through
Unicode uppercase expansion. Lowercase and legal line wrapping normalize to
the same semantic sequence-set digest; the raw FASTA digest still identifies
the exact input bytes.

`parse_cdhit_membership_csv()` accepts exactly
`cdhit_cluster_membership@1`:

```text
cluster_id,member_id,representative_id,is_representative,identity_to_representative,member_length
```

Every non-empty cluster must contain exactly one representative, every row in
that cluster must name it, and its representative row must have
`identity_to_representative=1.000000`. Member ids are globally unique.
Candidate FASTA and membership must contain exactly the same ids, and every
declared member length must equal the bound sequence length. A representative
summary such as `cluster_id,representative,member_count` is legacy and is
rejected.

## Canonical graph artifacts

Nodes use `aox_candidate_graph_nodes@1` and these exact columns:

```text
node_id,sequence_digest,sequence_length,cluster_id,representative_id,is_representative,identity_to_representative,candidate_fasta_digest,candidate_sequence_set_digest,cdhit_membership_digest,cdhit_membership_set_digest,cdhit_membership_schema_id,node_schema_id,similarity_calculation_id,similarity_calculation_digest,similarity_implementation_digest
```

Edges use `aox_candidate_graph_edges@1` and these exact columns:

```text
source,target,source_sequence_digest,target_sequence_digest,source_cluster_id,target_cluster_id,alignment_score_half_units,identity_matches,identity_aligned_residues,similarity_ppm,similarity,similarity_threshold_ppm,candidate_sequence_set_digest,cdhit_membership_set_digest,cdhit_membership_schema_id,edge_schema_id,similarity_calculation_id,similarity_calculation_digest,similarity_implementation_digest
```

Nodes are ordered lexically by sequence id. Edges are ordered by lexical
source/target combinations and are emitted only when exact rational identity
meets the integer-ppm threshold. The comparison uses cross multiplication;
binary floating-point cannot move a pair across the threshold.

Pair indexes are generated in lexical `(source_id,target_id)` order. Fewer than
`128` pairs use the same-process loop. At `128` or more pairs, the input is
parallel-eligible. Worker count is the minimum of pair count, hard maximum
`16`, available `os.sched_getaffinity(0)` capacity (or `os.cpu_count()` only
when affinity is unavailable), and every available cgroup v2/v1 quota divided
by its period and rounded up. The inspected sources are cgroup v2 `cpu.max`
and cgroup v1 `cpu.cfs_quota_us`/`cpu.cfs_period_us` under both `cpu` and
`cpu,cpuacct`. Unbounded quota contributes no extra limit; any present but
unreadable, incomplete, or malformed constraint fails closed. A worker count
of `1` selects the serial loop before execution; only a count greater than `1`
starts a bounded `ProcessPoolExecutor` with `chunksize=64`. Worker input is the
already validated/index-encoded sequence tuple. `executor.map()` preserves
input order, and filtering below-threshold pairs therefore preserves canonical
edge order independently of worker completion order. Pool creation, worker,
serialization or result failure after the parallel branch begins raises
`scientific_prerequisite_missing:similarity_parallel_execution_failed`; there
is no hidden serial retry or fallback after the parallel branch has begun.

The canonical `aox_candidate_similarity_graph_manifest@1` records the input
byte and semantic-set digests, schema/calculation/implementation identities,
threshold, node/edge artifact digests and counts, plus empty-result status.
`validate_graph_artifacts()` reparses the FASTA and membership, recalculates
every eligible edge, compares every node/edge field, verifies canonical bytes,
and then verifies the manifest closure. It does not contact a provider.

Legacy `node_id,label,score,cluster_id`, three-column constant edge files, a
copied `0.91`, a constant cluster id, a changed sequence digest, missing or
duplicate membership, malformed schema, or digest drift all fail closed.

## Empty result

When the real motif filter yields no candidates:

- candidate FASTA is empty;
- membership is a header-only `cdhit_cluster_membership@1` CSV;
- nodes and edges are header-only canonical CSVs;
- the manifest has `empty_result=true`, zero counts, and a non-empty stable
  lowercase reason code such as `no_candidates_after_motif_filter`.

No placeholder node, representative, cluster, edge, sequence, or score is
allowed. A one-candidate graph is not an empty scientific result: it contains
one real node and a schema-valid header-only edge artifact.

## Real-data diagnostics and final current-backend receipt

The historical pure-v3 diagnostic at
`/tmp/openzyme-aox-similarity-diagnostic-20260720-final-v3/receipt.json`
(`sha256:caf483bedbe2865cdf3be0677dbcb3a27d6ccfb9fd1a57bbc0093a35ef90bcf5`)
used the superseded implementation/calculation identities
`sha256:9df7a2afb72ae46473fc20c0a8ceb7b5d3f83ad5e2144bfebeb9bbd88800548d`
and
`sha256:31df5ca6eaf079073bd290550f70646f2ab845faf2dcdae43ffb3fff0c3a7499`.
It parsed the real HMMalign AFA and UniProt target bytes, observed 516
candidates, 513 unique sequence digests, 132,870 pairs, 516 nodes and 13,778
edges, and ran the old affinity-only 16-worker graph in `2929.494427s`.
Its 32-real-pair former-tuple-oracle comparison took `16.717732s` with zero
mismatch. This ordinary `/tmp` receipt and its synthetic membership are
explicitly `non_cutover=true`; the old identities are historical only and MUST
NOT be used as current workflow pins.

The temporary real Podman `--cpus=2` calibration receipt at
`/tmp/openzyme-aox-bio-podman-audit/comparison-receipt.json`
(`sha256:b9749e6c3f23dd553a1e33b55f7cb9a67a1aee6dfbfae8fb4235ce0aa52f563c`)
used Python `3.12.13`, Biopython `1.87`, and NumPy `2.4.4`. On the same 516
sequences/132,870 pairs, an affinity-only 16-worker run took `168.766s`, while
the cgroup-equivalent forced 2-worker run took `84.087s` (`2.007x` faster);
both produced 13,778 edges. The 32-pair tuple digest and canonical
nodes/edges/manifest bytes matched the pure-v3 diagnostic, and the observed
packed bound `15,665,525,262` remained strictly below `2^53`. This proves the
need for the bounded cgroup correction and that the fixed 2-CPU/3600s sandbox
need not be enlarged. It remains an ordinary, unsealed, non-cutover
calibration receipt.

The final independent current-backend diagnostic is
`/tmp/openzyme-aox-final-backend-podman-20260720/aggregate-comparison-receipt.json`,
schema `aox_production_final_backend_comparison_receipt@1`, digest
`sha256:ace8baa8bfa070a621186d7b3db3acddcdf39abe26070e72270fc727b0017b5e`,
and `non_cutover=true`. It binds candidate FASTA
`sha256:78b0416ee68373d226a5ead03ab55806ae00b24283d3d6cd878309500a8c9839`
and membership
`sha256:ba31cdda2aa08b00b0c592840838e8ba6173dc1de9c1ac041397bf9f2ebf28d4`
to the current implementation/calculation identities.

Two independent authoritative-production-source, no-monkeypatch runs used the
same immutable image
`sha256:a581e59d462556186f4cb7cd98587d17307159af58135155596ca54e6c6a7eb2`,
Python `3.12.13`, Biopython `1.87`, exact cutover NumPy `2.4.4`, affinity and
`os.cpu_count()` of `16`, cgroup `cpu.max="200000 100000"`, and effective
worker count `2`. Biopython and NumPy distribution-record digests were
`sha256:df12d09072ff0f4e999cf22864183a3e12fac0337200a5af916535c00cc64873`
and
`sha256:8c29c383eeb00847bde76cfc46c4e1a112c9f070d897fddaec3c6b4fb4436123`;
the comparison-driver digest was
`sha256:9c91d9350e2490ceccb872c7a9f51cc11c200af9383b1eeaed4494411dec42ac`,
and the no-monkeypatch per-run production-source script digest was
`sha256:f9e2c62e1850ee06d53a38ec015ef3517f2a90ff38d9d0178a4d267668ec8421`.
Run receipts
`sha256:e48ab741b511aa40e3b056421b3222245ca4e0de2a16eda5843663603d423234`
and
`sha256:e3e89cd85e9cf99756b0fba7ba329baa03cb746d3bcf1993193b282be4f4453b`
each processed 516 nodes, 132,870 pairs, and 13,778 edges. Graph/total times
were `393.206478s` / `393.835379s` and `397.540161s` / `398.171785s`;
maximum self-or-child RSS was `91,476` and `91,424` KiB.

Both runs produced byte-identical current-contract outputs: nodes
`sha256:61d35a8ef6181c48308a26ecc0a5ba920e38f882e82fdfec06c685e27a5ebc0b`,
edges
`sha256:f6be204c3df5684b7369d8fde0daa9ed911778f38d6753ec5b3cd0beedd407ee`,
and manifest
`sha256:9f5f162714bb8aa094b589d90516ba55d63577146073c89eacb020378c351225`.
After requiring and rewriting only the named calculation/implementation pin
fields and their pin-induced manifest artifact-digest closure, both runs are
byte-identical to the historical pure-v3 nodes/edges/manifest digests above;
all edge endpoints and non-pin fields are equal. Rewrite counts are exactly
516 node rows, 13,778 edge rows, and four manifest fields per run.

Production exposes no correction-activation counter and the authoritative
runs forbade wrapping, so the receipt records activation count as
`status="unavailable"` with that reason; it does not invent zero. The earlier
reference-validation environment used NumPy `2.4.6`, while both final full-set
runs used the cutover pin `2.4.4`. This is deliberately not described as a
direct full-set patch-version A/B run or as environment equality: reference
`2.4.6` remains validation context, cutover accepts only `2.4.4`, and no version
fallback exists. The repeatability and old-v3 normalized-equivalence receipt
closes the r26 diagnostic/knowledge-pin gate, but its ordinary `/tmp`, unsealed
status does not satisfy either positive live attempt or change the campaign
from NO-GO.

## SDK use

```python
from openzyme_pipeline import aox_similarity

graph = aox_similarity.build_similarity_graph(
    candidate_fasta_bytes,
    cdhit_membership_bytes,
    threshold_ppm=850_000,
    expected_calculation_id=aox_similarity.CALCULATION_ID,
    expected_calculation_digest=aox_similarity.CALCULATION_DIGEST,
    expected_implementation_digest=aox_similarity.IMPLEMENTATION_DIGEST,
)

nodes_csv = graph.nodes_csv()
edges_csv = graph.edges_csv()
manifest_json = graph.manifest_json()
```

The Host artifact boundary still owns sealing and provenance links to the
controlled CD-HIT operation. This SDK contract supplies deterministic bytes
and network-free recomputation; it does not turn unsealed local files into
evidence.
