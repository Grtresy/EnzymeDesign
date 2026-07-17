# AOX real-sequence similarity and graph contract v1

`openzyme_pipeline.aox_similarity` owns the dependency-free
`aox_global_sequence_identity@1` calculation and the canonical AOX candidate
graph schemas. It is a pure scientific calculation and verifier inside the
sandbox SDK; it does not own task, approval, operation, artifact, or report
state.

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

Callers bind all of:

- `CALCULATION_ID`;
- `CALCULATION_DIGEST`;
- `IMPLEMENTATION_DIGEST`.

`calculation_payload()` is the canonical digest payload. Workflow manifests
must pin the values, and `build_similarity_graph()` or
`validate_graph_artifacts()` must receive the expected values at the
fail-closed boundary. A mismatch fails before graph rows are returned.

## Canonical inputs

`parse_candidate_fasta()` accepts gap-free protein FASTA. Identifiers must be
unique ASCII ids and residues must be supported by the embedded BLOSUM62
alphabet. Lowercase and line wrapping normalize to the same semantic sequence
set digest; the raw FASTA digest still identifies the exact input bytes.

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
