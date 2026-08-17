# AOX Candidate Similarity Graph v1

`openzyme_pipeline.aox_similarity.build_similarity_graph` deterministically builds nodes, edges and a manifest from
the exact full post-motif, pre-clustering candidate set plus explicit CD-HIT membership.

Contracts:

- `cdhit_cluster_membership@1` binds representative/member identity;
- `aox_candidate_graph_nodes@1` binds every candidate node and annotations;
- `aox_candidate_graph_edges@1` binds normalized pair identity and similarity values;
- `aox_candidate_similarity_graph_manifest@1` binds input set, serializer, schemas and output digests.

The representative-only FASTA cannot replace the full node universe. Reject missing/extra/duplicate candidate,
membership-set drift (`candidate_membership_set_mismatch`), self/duplicate edge ambiguity, noncanonical ordering,
invalid numeric values and digest drift.

The calculation has no external I/O. Caller-owned output files must be published and validated as exact revision paths;
scientific adoption binds them to the successful producer occurrence.
