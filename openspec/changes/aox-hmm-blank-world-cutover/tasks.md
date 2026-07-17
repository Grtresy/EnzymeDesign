## 1. Reference and contract baseline

- [x] 1.1 Record the authorized notebook/runner hashes, formula-derived golden rows, corrected integer-tenths boundary, and historical-output caveats without copying reference outputs into live roots.
- [x] 1.2 Implement the dependency-free `aox_motif_rule_score@1` contract, digest identities, aligned FASTA parser, exact coordinate mapping, scoring, and canonical row serialization in `openzyme_pipeline`.
- [x] 1.3 Add minimal immutable golden fixtures and focused tests for exact score/pass/order plus missing, duplicate, truncated, unequal-width, digest-drift, and legacy-schema failures.
- [ ] 1.4 Add a versioned real-sequence similarity calculation and parsers that bind graph nodes/edges to actual sequence and CD-HIT identities, including schema-valid empty output.
- [ ] 1.5 Replace AOX validators and execution summary fields with the canonical motif contract and reject `activity_score`, `seq_score`, `pass_rule`, constant graph data, and synthetic sequences as cutover evidence.

## 2. Harness workflow-selection friction

- [x] 2.1 Add explicit `workflow_refs` subset selection to `task.delegate`, validate authorization and target-role requirements before claim, and persist the exact manifest snapshots.
- [x] 2.2 Remove implicit parent-focus workflow inheritance so omitted/empty refs mean no binding; return LLM-readable errors for unauthorized, duplicate, drifted, or incompatible refs.
- [x] 2.3 Add harness/protocol tests for executor-only binding, researcher/reporter no-binding, explicit empty selection, role mismatch, manifest drift, and durable replay.
- [x] 2.4 Document the corrected delegation contract in `docs/v3/` and, for every newly found large harness issue, create one detailed `docs/v3/architecture-proposals/` document without implementing that proposal.

## 3. Literature provider quorum

- [ ] 3.1 Introduce typed provider outcome/provenance/failure records and a bounded HTTP policy that handles safe request identity, timeouts, retryable status, `Retry-After`, attempts, schema drift, empty results, response digest, and retrieval time.
- [ ] 3.2 Update PubMed normalization to preserve PMID, supplied DOI, title, authors, venue/date, source locator, NCBI identity, request/response provenance, and to distinguish empty results from schema drift.
- [ ] 3.3 Update Semantic Scholar and Tavily adapters so rate limiting, exhaustion, absence, and empty results persist explicit enrichment degradation without synthetic fallback.
- [ ] 3.4 Establish invocation/operation state before provider I/O, terminate it on every outcome, convert typed failures to LLM-readable tool results, and seal licensed/safe provider evidence through the artifact boundary.
- [ ] 3.5 Wire Host settings so PubMed/Semantic Scholar remain usable without Tavily and secrets/private URLs never enter errors, evidence, or public projections.
- [ ] 3.6 Add tests for 429/`Retry-After`, transient recovery, non-retryable status, empty-vs-schema drift, required-vs-enrichment quorum, terminal invocation, real sealing, repository round-trip, and safe projection.

## 4. AOX provider and toolchain identity chain

- [ ] 4.1 Make NCBI fetch prove requested-to-resolved identity for all 13 references, including `9AVH_A`, and fail on missing, duplicate, or mismatched records while sealing aggregate and per-sequence digests.
- [ ] 4.2 Strictly validate EBI HMMER `refprot` hits, bind candidates to UniProt accessions, and preserve request/operation, page, raw/parsed response, numeric field, and digest provenance.
- [ ] 4.3 Preserve UniProt reviewed status, release/version, retrieved time, response and sequence digests; express cross-database mappings as annotations and require explicit choice on sequence mismatch.
- [ ] 4.4 Migrate the AOX sandbox execution to consume real provider/HPC outputs through `openzyme_pipeline`, run MAFFT/hmmbuild/hmmalign/CD-HIT/scoring/similarity, and emit normalized sealed artifacts without constants or copied scores.
- [ ] 4.5 Add provider/toolchain tests for reference completeness, HMMER schema/empty results, UniProt identity conflicts, tool params/versions, output declarations, graph lineage, and empty-result reporting.

## 5. Workflow, product path, and reporting

- [ ] 5.1 Version and digest-pin AOX workflow knowledge for the required accessions, provider quorum, scoring contract, artifact schemas, empty-result semantics, and scientific fail-closed conditions while preserving agent strategy freedom.
- [ ] 5.2 Replace the single-executor S15 live scenario with a one-message canonical master path that delegates researcher/executor/reporter work and advances only through public message, runtime drain, approval, workspace, event, and report APIs.
- [ ] 5.3 Require explicit task business exits, canonical approval continuity, normalized artifact registration, report claim/source links, `report.publish`, final master response, and research/execution/report participation in cutover validation.
- [ ] 5.4 Quarantine deterministic/seeded AOX fixtures as `fixture_non_cutover`, remove historical live-passed claims, and ensure seeded smoke cannot satisfy the cutover validator.
- [ ] 5.5 Update Host API projections and Web UI to show safe provider/quorum/operation/artifact/report/evidence status and preserve the same operation identity across approval resume.
- [ ] 5.6 Add API/eval/UI tests for required/degraded evidence, approval continuity, published report, fixture rejection, empty scientific result, and projection secrecy.

## 6. Blank-world evidence and campaign

- [ ] 6.1 Implement blank-world preflight that creates and proves unique empty SQLite/blob/artifact/sandbox/HPC roots, records allowed immutable prerequisites, bypasses evidence-bearing caches, and rejects preloaded science.
- [ ] 6.2 Implement canonical attempt bundles covering commit/config/workflow/scoring/image/SDK/provider/toolchain, clean roots, approvals, operations, tasks, artifacts, report, final answer, warnings, degradation, and outcome.
- [ ] 6.3 Implement a network-free verifier that recomputes canonical bundle/artifact/scoring/lineage/report digests and reports the exact missing or mismatched identity.
- [ ] 6.4 Add tamper tests for artifact bytes, provenance, operation, report, and bundle fields plus secret/path leakage tests.
- [ ] 6.5 Implement independent known-positive provider/HPC probes and keep probe inputs/results out of formal AOX result artifacts; distinguish healthy empty result from discovery.
- [ ] 6.6 Implement a campaign driver that enforces two independent positive attempts on one commit/config identity followed by one controlled required-chain fault attempt and derives GO only from all three verified digests.
- [ ] 6.7 Integrate the existing persistent MICU 100M ledger without reset and record pre/post snapshots for every real attempt.

## 7. Architecture and operator documentation

- [ ] 7.1 Synchronize `docs/OpenZyme架构设计.md`, relevant stable `docs/v3/` documents, AOX execution docs, workflow pack docs, live marker semantics, operator commands, and current limitations with the implementation.
- [ ] 7.2 Rewrite the S15 session evidence as historical/non-cutover and document the corrected formula, integer boundary, real provider quorum, blank-world proof, fixture boundaries, and local trusted-Host scope.
- [ ] 7.3 Audit all implementation-time harness findings, directly test/document only small corrections, and create separate detailed deferred documents for each major architecture adjustment without implementing them.

## 8. Verification and cutover decision

- [ ] 8.1 Run scoring/provider/harness/execution/campaign focused tests and ruff, then fix every regression without weakening scientific gates.
- [ ] 8.2 Run frontend tests/build, default non-live pytest, `./scripts/check-mainline.sh`, and `uv run python -m openzyme_host_api.evals` from a clean configuration boundary.
- [ ] 8.3 Preflight NCBI/PubMed/EBI/UniProt, MICU, image/SDK, HPC runner/toolchain, and Chrome availability while recording exact blocker evidence.
- [ ] 8.4 Run positive attempt 1 from clean roots and require published report plus passed offline verification.
- [ ] 8.5 Run positive attempt 2 from different clean roots on the identical commit/config and require published report plus passed offline verification.
- [ ] 8.6 Use Chrome for at least one canonical approval and verify same-operation resume, workspace/events/report/evidence consistency, and a clean browser console.
- [ ] 8.7 Run the controlled fail-closed attempt and prove it produces neither a cutover-eligible report nor a valid success bundle while preserving terminal failure evidence.
- [ ] 8.8 Seal the three-attempt campaign decision, report MICU cumulative usage, audit git status/diff and commits, and declare local Live cutover GO only if every criterion passes; otherwise retain precise NO-GO blockers.
