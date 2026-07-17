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
