# AOX/HMM Live Cutover Workflow Knowledge

This document is the domain SOP for the explicitly selected workflow reference
`workflow:aox-hmm-live@1.0.0#sha256:<manifest-digest>`. It is not a generic harness prompt rule and must
not be selected by matching words in a user message, task subject, or
delegation instructions.

The structured workflow manifest pins this document by `doc_id`, `version`, and
`content_sha256`. The harness must reject a missing document, version mismatch,
or digest mismatch before a model/provider call. `docs.search` and `docs.read`
return the current version and digest; callers may pass both values back to
`docs.read` for an exact fail-closed read.

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

Required controlled operations:

- `bio.ncbi_fetch_proteins`
- `bio.uniprot_fetch`
- `bio.hmmer_search(database="refprot")`
- `bio_tools.cdhit`
- `bio_tools.mafft`
- `bio_tools.hmmbuild`
- `bio_tools.hmmalign`
- `hpc.workspace`
- `hpc.stage_artifact`
- `hpc.fetch_outputs`
- `artifacts.register`

## Scientific prerequisites

The cutover input contains these 13 reference accessions:

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

The search route is EBI HMMER REST against `refprot`. Candidate filtering uses
observed provider fields only: sequence length from 650 through 700 inclusive
and HMM score strictly greater than 200.

The downstream activity filter (`reference_coordinate="AAB57849.1"`, threshold
33.6) is a separate scientific scoring contract. A run may claim this workflow
passed only when a versioned scoring implementation or an authorized,
provenance-linked scoring artifact supplies the actual per-sequence score and
calculation summary. The current SDK operation list does not itself define that
scoring transform. If neither input is available, return
`scientific_prerequisite_missing`; do not manufacture `40-index`, copy HMM
scores into activity scores, or set `pass_rule=true` by construction.

Likewise, every similarity value and cluster id must come from declared tool
output or a versioned, auditable calculation. Do not emit constant `0.91` edges
or a constant cluster id.

No real HMM hits, no fetched target sequences, or no candidates after the real
filters is a legitimate scientific empty result. Record it as a structured
`empty_result` with the provider/tool observations and do not substitute the
reference accessions to make the result non-empty. An empty result is not live
cutover `passed` unless the versioned acceptance contract explicitly supports
that outcome.

## Registered deliverable contract

A passed run registers exactly these normalized final relative paths, all
derived from the current controlled-operation evidence:

- `aox_hmm/AOX_ref21.fasta`
- `aox_hmm/target.fasta`
- `aox_hmm/AOX_ref.hmm`
- `aox_hmm/hits_raw.csv`
- `aox_hmm/hits_len650_700_200.csv`
- `aox_hmm/scored_ref_plus_hits.csv`
- `aox_hmm/AOX_candidates.fasta`
- `aox_hmm/AOX_candidates_cdhit85.fasta`
- `aox_hmm/nodes.csv`
- `aox_hmm/edges_similarity.csv`
- `aox_hmm/execution_summary.json`

The normalized CSV schemas are:

- `hits_raw.csv`: `target`, `uniprot_accession`, `hmm_score`, `evalue`, `length`
- `hits_len650_700_200.csv`: the raw columns plus `sequence`
- `scored_ref_plus_hits.csv`: `id`, `seq_score`, `pass_rule`, `activity_score`,
  `reference_coordinate`, plus a calculation/provenance reference
- `nodes.csv`: `node_id`, `label`, `score`, `cluster_id`
- `edges_similarity.csv`: `source`, `target`, `similarity`

`execution_summary.json` records the accession count, candidate count, fixed
thresholds, `hmmer_database="refprot"`, provider/tool status, warnings,
registered artifact ids, normalized final paths, and the scoring/similarity
implementation version and digest. A summary cannot turn missing or synthetic
evidence into success.

## Executor sequence

1. Confirm the selected workflow id, version, manifest digest, and this
   document's version/digest from the structured workflow context.
2. Inspect the persistent sandbox workspace and author the pipeline source.
3. Dry-run or inspect the controlled operation plan and approval requirements.
4. Execute provider and HPC/tool operations through the SDK, using only
   artifact ids and Host-supervised staging/fetch.
5. Parse actual registered provider/tool outputs. Missing required fields,
   malformed data, digest drift, or a missing scientific scoring prerequisite
   stops the path with a structured error.
6. Register normalized outputs only after their real provenance and required
   schemas validate.
7. Mark the task completed only when every required passed-run deliverable and
   its provenance exists. Otherwise finish as blocked/failed, or report a
   structured empty result according to the selected acceptance contract.

Provider and HPC SDK responses expose registered output ids through the current
adapter/result envelope, not Host paths. `artifacts.get` may be used to locate a
registered relative path; `artifacts.materialize` creates the authorized input
target. Never infer a storage path from a public payload.
