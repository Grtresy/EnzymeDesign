# openzyme-pipeline

Container-side SDK for V3 execution pipeline code. The SDK communicates with the
Host supervisor through `/openzyme/control.sock` by default and never exposes
Host storage paths to pipeline code.

## AOX motif scoring

`openzyme_pipeline.aox_motif` implements the immutable
`aox_motif_rule_score@1` reference-coordinate heuristic. It parses aligned
FASTA bytes, resolves exactly one `AAB57849.1` record, calculates scores as
integer tenths, and emits deterministic canonical rows or CSV. The serialized
`motif_rule_score` is a fixed one-decimal string; the authoritative numeric
value is `motif_rule_score_tenths`, and the pass threshold is exactly `336`.

Callers should pin both `CONTRACT_DIGEST` and `IMPLEMENTATION_DIGEST` and pass
the expected values to `score_aligned_fasta`. Missing scientific inputs,
ambiguous coordinates, and digest drift raise `ScientificPrerequisiteError`
before any scored output is returned. This is a motif heuristic, not an
experimental activity prediction.

## AOX sequence similarity and graph validation

`openzyme_pipeline.aox_similarity` implements
`aox_global_sequence_identity@1` with a dependency-free, exact-integer global
affine-gap BLOSUM62 alignment. It binds real candidate FASTA sequence digests
to one-member-per-row `cdhit_cluster_membership@1` identities and emits
canonical versioned node, edge, and manifest artifacts. CD-HIT representative
identity and recalculated pairwise identity remain distinct observations.

`build_similarity_graph` derives every edge from sequence bytes;
`validate_graph_artifacts` reparses and recomputes the full graph closure
without network access. Header-only canonical nodes/edges are supported only
for an explicit scientific empty-result reason. Legacy graph schemas,
constant/copied weights, membership mismatch, sequence/digest drift, and
synthetic placeholder rows fail closed.
