# AOX Motif Rule Score v1

`openzyme_pipeline.aox_motif.score_aligned_fasta` is a deterministic calculation over an exact aligned FASTA and a
pinned coordinate-reference identity. It performs no provider, Git, runner or Host I/O.

The contract binds reference accession, alignment digest, coordinate mapping, accepted residue rules, score columns,
serializer identity and implementation digest. Output rows preserve input candidate identity and use the canonical
column order exported by `openzyme_pipeline.aox_motif.CANONICAL_COLUMNS`.

Reject duplicate/missing reference records, ambiguous coordinate mapping, illegal residues, inconsistent alignment
length, unexpected candidates, digest drift and noncanonical output. Unknown/malformed input is not a negative score.

The caller writes output into its current workspace, publishes an immutable revision, and binds the resulting path to
the exact successful producer adoption during scientific finalization. A local CSV path alone is not evidence.
