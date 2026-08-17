# AOX/HMM File-first Scientific Workflow

## Status

本文件描述 current file/revision contract，不授权 live campaign。任何新的 formal attempt 都必须从 current
workflow registry、authority、public API 和 source-bound evidence 建立；历史 numbered campaign、旧 catalog
receipt 和 historical import 均不可采用。

## Fixed reference set

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

PubMed supplies the required literature evidence. NCBI supplies one exact 14-record protein FASTA aggregate
including the coordinate reference. EBI HMMER REST supplies the real `refprot` search receipt. UniProt supplies
candidate identity and sequence/length join data. Semantic Scholar and Tavily are enrichment only.

## Workflow

1. publish exact research/reference inputs as an immutable revision;
2. create and admit the formal scientific attempt and exact operation universe;
3. run provider/compute operations through controlled-operation or revision-bound job owners;
4. use installed calculations:
   `aox_hmm_reference_set_selection@1`, `aox_reference_selection@1`,
   `aox_scoring_input_assembly@1`, `hmmer_score_filtered_accessions@1`,
   `aox_sequence_length_join@2`, `aox_motif_rule_score@1`,
   `hmmer_afa_alignment_canonicalization@1`, `cdhit_cluster_membership@1`,
   `aox_candidate_graph_nodes@1`, `aox_candidate_graph_edges@1`, and
   `aox_candidate_similarity_graph_manifest@1`;
5. record every occurrence disposition and adopt exact successful producer effects;
6. publish the result revision and call `scientific.deliverables.finalize` with all fixed paths, roles,
   format contracts and producer adoptions;
7. close selection/attempt only after immutable validation receipt and quiescence;
8. publish report and explicitly finish tasks as separate actions.

## File identity

Every input/output is bound by publication ref, commit, tree, normalized path, Git blob or LFS OID, actual content
digest and size. Mutable workspace paths, copied filenames and historical refs cannot satisfy the identity.

The full post-motif, pre-clustering candidate set is the source for graph nodes. The representative-only
`aox_hmm/AOX_candidates_cdhit85.fasta` is not an equivalent substitute. Membership drift fails with
`candidate_membership_set_mismatch`.

## Healthy empty

`scientific_outcome.status="empty"` is valid only when an installed deterministic calculation produces an exact typed
zero receipt with contract/implementation/output digests and stable reason. Provider failure, unknown effect, missing
file, parsing error or unresolved accession is blocked, not empty.

## Scientific fail-closed matrix

Block closure for occurrence/universe drift, unknown effect, source revision drift, missing adoption, publication or
LFS mismatch, format/role/path mismatch, non-exact reference set, ambiguous sequence join, graph membership drift,
stale authority, quiescence mismatch or historical import. Job success alone and local path presence are insufficient.
