## 1. Reference and contract baseline

- [x] 1.1 Record the authorized notebook/runner hashes, formula-derived golden rows, corrected integer-tenths boundary, and historical-output caveats without copying reference outputs into live roots.
- [x] 1.2 Implement the dependency-free `aox_motif_rule_score@1` contract, digest identities, aligned FASTA parser, exact coordinate mapping, scoring, and canonical row serialization in `openzyme_pipeline`.
- [x] 1.3 Add minimal immutable golden fixtures and focused tests for exact score/pass/order plus missing, duplicate, truncated, unequal-width, digest-drift, and legacy-schema failures.
- [x] 1.4 Add a versioned real-sequence similarity calculation and parsers that bind graph nodes/edges to actual sequence and CD-HIT identities, including schema-valid empty output.
- [x] 1.5 Replace AOX validators and execution summary fields with the canonical motif contract and reject `activity_score`, `seq_score`, `pass_rule`, constant graph data, and synthetic sequences as cutover evidence.

## 2. Harness workflow-selection friction

- [x] 2.1 Add explicit `workflow_refs` subset selection to `task.delegate`, validate authorization and target-role requirements before claim, and persist the exact manifest snapshots.
- [x] 2.2 Remove implicit parent-focus workflow inheritance so omitted/empty refs mean no binding; return LLM-readable errors for unauthorized, duplicate, drifted, or incompatible refs.
- [x] 2.3 Add harness/protocol tests for executor-only binding, researcher/reporter no-binding, explicit empty selection, role mismatch, manifest drift, and durable replay.
- [x] 2.4 Document the corrected delegation contract in `docs/v3/` and, for every newly found large harness issue, create one detailed `docs/v3/architecture-proposals/` document without implementing that proposal.

## 3. Literature provider quorum

- [x] 3.1 Introduce typed provider outcome/provenance/failure records and a bounded HTTP policy that handles safe request identity, timeouts, retryable status, `Retry-After`, attempts, schema drift, empty results, response digest, and retrieval time.
- [x] 3.2 Update PubMed normalization to preserve PMID, supplied DOI, title, authors, venue/date, source locator, NCBI identity, request/response provenance, and to distinguish empty results from schema drift.
- [x] 3.3 Update Semantic Scholar and Tavily adapters so rate limiting, exhaustion, absence, and empty results persist explicit enrichment degradation without synthetic fallback.
- [x] 3.4 Establish invocation/operation state before provider I/O, terminate it on every outcome, convert typed failures to LLM-readable tool results, and seal licensed/safe provider evidence through the artifact boundary.
- [x] 3.5 Wire Host settings so PubMed/Semantic Scholar remain usable without Tavily and secrets/private URLs never enter errors, evidence, or public projections.
- [x] 3.6 Add tests for 429/`Retry-After`, transient recovery, non-retryable status, empty-vs-schema drift, required-vs-enrichment quorum, terminal invocation, real sealing, repository round-trip, and safe projection.
- [x] 3.7 Preserve bounded iterative PubMed strategy while requiring exactly one primary artifact adoption in researcher `task.finish`, close nullable task/invocation/artifact/source lineage in collector/blocker/offline verifier, and defer complete invocation-history sealing to its own architecture proposal.

## 4. AOX provider and toolchain identity chain

- [x] 4.1 Make one NCBI fetch prove exact requested-to-resolved identity for all 14 inputs (13 HMM references including `9AVH_A` plus `AAB57849.1`), split them through the versioned 13-record model-reference and single-record coordinate-reference contracts, and fail on missing, extra, duplicate, or mismatched records while sealing aggregate and per-sequence digests.
- [x] 4.2 Strictly validate EBI HMMER `refprot` hits, derive the exact score-`>200` UniProt accession artifact before any UniProt call, and preserve request/operation, page, raw/parsed response, numeric field, and digest provenance.
- [x] 4.3 Preserve UniProt reviewed status, release/version, retrieved time, response and sequence digests; express cross-database mappings as annotations and require explicit choice on sequence mismatch.
- [x] 4.4 Migrate the AOX sandbox execution to consume real provider/HPC outputs through `openzyme_pipeline`, build the HMM only from the exact 13 references, assemble `AAB57849.1`-first scoring input from post-UniProt targets, run reached MAFFT/hmmbuild/hmmalign/CD-HIT/scoring/similarity operations, and emit normalized sealed artifacts without constants or copied scores.
- [x] 4.5 Add provider/toolchain tests for exact-14 reference completeness and split, HMMER schema/score-filter/upstream-empty receipt, UniProt identity/length-join conflicts, reached-branch operation omission, tool params/versions, output declarations, graph lineage, and empty-result reporting.

## 5. Workflow, product path, and reporting

- [x] 5.1 Version and digest-pin AOX workflow knowledge for the required accessions, provider quorum, scoring contract, artifact schemas, empty-result semantics, and scientific fail-closed conditions while preserving agent strategy freedom.
- [x] 5.2 Replace the single-executor S15 live scenario with a one-message canonical master path that delegates researcher/executor/reporter work and advances only through public message, runtime drain, approval, workspace, event, and report APIs.
- [x] 5.3 Require explicit task business exits, canonical approval continuity, normalized artifact registration, report claim/source links, `report.publish`, final master response, and research/execution/report participation in cutover validation.
- [x] 5.4 Quarantine deterministic/seeded AOX fixtures as `fixture_non_cutover`, remove historical live-passed claims, and ensure seeded smoke cannot satisfy the cutover validator.
- [x] 5.5 Update Host API projections and Web UI to show safe provider/quorum/operation/artifact/report/evidence status and preserve the same operation identity across approval resume.
- [x] 5.6 Add API/eval/UI tests for required/degraded evidence, approval continuity, published report, fixture rejection, empty scientific result, and projection secrecy.

## 6. Blank-world evidence and campaign

- [x] 6.1 Implement blank-world preflight that creates and proves unique empty SQLite/blob/artifact/sandbox/HPC roots, records allowed immutable prerequisites, bypasses evidence-bearing caches, and rejects preloaded science.
- [x] 6.2 Implement canonical attempt bundles covering commit/config/workflow/scoring/image/SDK/provider/toolchain, clean roots, approvals, operations, tasks, artifacts, report, final answer, warnings, degradation, and outcome.
- [x] 6.3 Implement a network-free verifier that recomputes canonical bundle/artifact/scoring/lineage/report digests and reports the exact missing or mismatched identity.
- [x] 6.4 Add tamper tests for artifact bytes, provenance, operation, report, and bundle fields plus secret/path leakage tests.
- [x] 6.5 Implement and verify `aox_known_positive_probe@2` with the fixed two-NCBI/two-UniProt globin identities and exact six provider/HPC operations, raw-response digests, isolated task/workspace/sandbox/source/artifact identities, and no probe flow into formal AOX results; distinguish healthy empty result from discovery.
- [x] 6.6 Implement a campaign driver that enforces two independent positive attempts on one commit/config identity followed by one controlled required-chain fault attempt and derives GO only from all three verified digests.
- [x] 6.7 Integrate the persistent MICU 500M ledger without reset, migrate the exact legacy 100M fixed policy while preserving all prior usage, keep caller-selected lower limits durable, and record pre/post snapshots for every real attempt.
- [x] 6.8 Bound `world.inspect.capabilities` to task-filtered invocation facts and capped refs so large tool outputs cannot overflow the agent context.
- [x] 6.9 Seal typed pipeline source directories as canonical self-verifying `openzyme_sealed_source_tree@1` envelopes and verify their internal/tree provenance offline.
- [x] 6.10 Add the strict `fasta_zero_records@1` artifact profile so only derived exact-zero FASTA can represent a healthy empty result and sentinels remain invalid.
- [x] 6.11 Bind formal evidence to exact durable role-scoped delegation/workflow receipts, publish the installed scientific callable/provider/fetch map, and reject approximation or path guessing.
- [x] 6.12 Require explicit bounded MICU context configuration and close the post-drain-response `waiting_approval` visibility race without changing stable failure taxonomy.
- [x] 6.13 Keep failed-coordinator cleanup active through the existing attempt deadline, retry transient cleanup reads/resolves without masking the primary blocker, reconcile selected-session pending approvals in the Web UI without stale overwrite or old-request starvation, and make the Chrome consumer ignore same-type activity projection echoes without a closed decision while treating an explicit rejected command decision as fail closed.
- [x] 6.14 Add strict direct-field artifact response selectors, require attempt-local completed-operation checkpoints after local parser/source errors, and reject duplicate-method or post-failure approvals before external dispatch without weakening the exact formal operation set.
- [x] 6.15 Correct the r14 AOX HMM-capable timeout hierarchy with `s09.exec_policy.v2` (`120s` default/`3600s` finite max), exact pre-dispatch HMMER run-policy validation, and a `7200s` minimum/default formal session bound; record durable async continuation and quiescent sealing separately without implementing it.

## 7. Architecture and operator documentation

- [x] 7.1 Synchronize `docs/OpenZyme架构设计.md`, relevant stable `docs/v3/` documents, AOX execution docs, workflow pack docs, live marker semantics, operator commands, and current limitations with the implementation.
- [x] 7.2 Rewrite the S15 session evidence as historical/non-cutover and document the corrected formula, integer boundary, real provider quorum, blank-world proof, fixture boundaries, and local trusted-Host scope.
- [x] 7.3 Audit all implementation-time harness findings, directly test/document only small corrections, and create separate detailed deferred documents for each major architecture adjustment without implementing them.

## 8. Verification and cutover decision

- [x] 8.1 Re-run scoring/provider/harness/execution/campaign focused tests and ruff after the pre-live harness closure, then fix every regression without weakening scientific gates.
- [x] 8.2 Re-run frontend tests/build, default non-live pytest, `./scripts/check-mainline.sh`, and `uv run python -m openzyme_host_api.evals` from a clean configuration boundary.
- [ ] 8.3 Preflight NCBI/PubMed/EBI/UniProt, MICU, image/SDK, HPC runner/toolchain, and Chrome availability while recording exact blocker evidence.
- [ ] 8.4 Run positive attempt 1 from clean roots and require published report plus passed offline verification.
- [ ] 8.5 Run positive attempt 2 from different clean roots on the identical commit/config and require published report plus passed offline verification.
- [ ] 8.6 Use Chrome for at least one canonical approval and verify same-operation resume, workspace/events/report/evidence consistency, and a clean browser console.
- [ ] 8.7 Run the controlled fail-closed attempt and prove it produces neither a cutover-eligible report nor a valid success bundle while preserving terminal failure evidence.
- [ ] 8.8 Seal the three-attempt campaign decision, report MICU cumulative usage, audit git status/diff and commits, and declare local Live cutover GO only if every criterion passes; otherwise retain precise NO-GO blockers.
