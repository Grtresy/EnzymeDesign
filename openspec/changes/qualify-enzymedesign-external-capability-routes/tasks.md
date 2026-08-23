## 1. Contracts and lifecycle boundaries

- [x] 1.1 Add immutable contracts for safe subject observations, discovery reports, identity gaps, resolution candidates and operator decisions
- [x] 1.2 Add exact Provider/target subject identity closures with canonical digest validation and no readiness-digest promotion
- [x] 1.3 Add dry-plan, per-occurrence and per-batch warning/hard budget, effect, cleanup, fault, TTL/storage and authorization contracts
- [x] 1.4 Add independent dry-plan verification and stable secret-safe failure codes for unresolved identity, budget and live-authorization blockers
- [x] 1.5 Export the new public contracts without adding Provider, SSH, scheduler or process dependencies to `openzyme-contracts`

## 2. Safe identity discovery and decision packet

- [x] 2.1 Implement an allowlist-only observer over explicit safe source projections with zero credential resolution, network, container, SSH, scheduler or scientific-process effects
- [x] 2.2 Bind readiness units to resolved, partial, missing, unsafe or drifted identity observations and affected profile/unit digests
- [x] 2.3 Generate mutually exclusive resolution candidates and a recommendation for each unresolved subject without selecting a candidate automatically
- [x] 2.4 Add operator decision validation that rejects unknown, stale, ambiguous or source-drifted candidate selections
- [x] 2.5 Produce a secret-safe current-checkout discovery and gap-resolution artifact for Batch 1 and AlphaFold Batch 2

## 3. Dry-plan composition and pre-effect guard

- [x] 3.1 Compose independent Batch 1 (`base`, `research-provider`, `hpc-primary`, `hmmer`, `docking`) and Batch 2 (`alphafold`) unit closures
- [x] 3.2 Implement generous warning/hard budget policies for LLM, Tavily, Provider HTTP, Git/LFS, Podman, Slurm and AlphaFold resources with `max_retries=0`
- [x] 3.3 Bind exact probe/fault sequence, isolated-effect allowlist, same-attempt reconcile, cleanup and risk-based TTL/storage policy into each dry plan
- [x] 3.4 Implement plan-only Adapter/Driver probe bridge metadata and an exact selected-binding factory guard
- [x] 3.5 Reject backend construction before credential resolution or effect unless a current occurrence authorization binds the exact dry-plan digest
- [x] 3.6 Generate independently verified dry plans whose unresolved units remain explicit blockers and whose `live_effect_authorized` value is false

## 4. Operator interfaces and protected evidence seams

- [x] 4.1 Add a CLI/script that consumes an explicit safe snapshot and emits canonical discovery, gap and dry-plan JSON without loading raw secret-bearing environment values
- [x] 4.2 Add a protected SQLite qualification-ledger interface and secret-safe receipt export model without creating real qualification receipts in plan-only mode
- [x] 4.3 Add private diagnostic-root references by `diagnostic_id` while excluding credential material, private paths, raw streams and tracebacks from public artifacts
- [x] 4.4 Update the protected manual workflow so its current job is plan-only and cannot enter a live backend without a future exact occurrence-authorization input

## 5. Verification and documentation

- [x] 5.1 Add deterministic contract tests for canonical digests, drift, stale decisions, profile closure, budget warning/hard limits, TTL and receipt tamper rejection
- [x] 5.2 Add canary tests proving discovery and dry-plan generation do not read or emit secrets and do not perform network, container, SSH, scheduler or scientific-process effects
- [x] 5.3 Add backend-factory tests proving missing/mismatched authorization fails before credential resolution with no retry or fallback
- [x] 5.4 Document identity discovery, operator decisions, generous circuit-breaker budgets, two-batch policy, protected evidence and the `qualified != cutover` boundary in architecture and operator docs
- [x] 5.5 Run focused tests, non-live qualification checks, strict OpenSpec validation and mainline verification on one source-bound checkout

## 6. First live-effect decision gate

- [x] 6.1 Present the exact current identity-gap solutions and independently verified Batch 1/Batch 2 dry plans to the operator
- [x] 6.2 Freeze the operator's source-bound candidate selections, including local-only Git/LFS, protected operator storage and AlphaFold Batch 2, without promoting any subject to resolved
- [x] 6.3 Split identity preparation from qualification, generate independently verified exact preparation plans and prove both backend factories remain pre-effect without their own authorization
- [x] 6.3a Bind every preparation action to one owner component, exact secret-safe input digest and at most one credential locator; reject input, owner and locator drift before resolver or builder access
- [x] 6.3b Implement the approved protected operator-state layout (`0700` root, `0600` files, no symlinks), exact credential-bundle resolver and safe preparation-result ledger
- [x] 6.3c Implement the seven Batch 1 owner actions: dedicated LLM/Tavily locators, local-only Git/LFS, three repository-owned image groups and qualification-only `Diannan/3090` identity observation/config
- [x] 6.3d Rebind post-preparation readiness units from non-live locator placeholders to exact qualification locators and prove safe results can drive effect-free rediscovery without issuing qualification evidence
- [x] 6.3e Add an idempotent root/layout-only bootstrap, canonical authorization writer and source-bound Batch 1 executor that preflights all exact locators before mutation, records every result, resumes only exact stored occurrences and emits `prepared_not_qualified` rediscovery evidence
- [ ] 6.4 Pause before credential resolution or any Provider, Git, container, SSH, Slurm, HPC or scientific-program effect and obtain explicit durable one-shot preparation authorization for an exact plan digest, batch and operator, with terminal no-redispatch and explicit revocation
- [ ] 6.5 After preparation and effect-free rediscovery, obtain a separate exact qualification occurrence authorization; preparation authority MUST NOT substitute

## 7. Future real qualification after authorization

- [ ] 7.1 Resolve approved Provider, Git/LFS, Podman image, HPC inventory/software and protected-storage identities and rebuild the source-bound plan
- [x] 7.2a Implement exact LLM, Tavily and public Bio HTTP Adapter bridges plus authorization-bound Distribution routing; verify request, route, subject, credential-locator and no-redispatch guards under fake Ports
- [x] 7.2b Add Git/LFS, Podman, SSH and Slurm owner bridge boundaries that reject component/route/subject drift, hosted Git sync, unpinned images, non-isolated resources and missing same-attempt reconciliation
- [ ] 7.2 Implement and verify Adapter-owned live probe bridges for LLM, Tavily, Bio HTTP, Git/LFS, Podman, SSH and Slurm without fallback
- [x] 7.3a Add Driver-owned formal-Compute-only binding guards for HMMER, Vina, fpocket and preprocessing; reject raw or binding-drifted operation Ports under deterministic fake execution
- [ ] 7.3 Implement and verify Driver-owned real smoke bridges for HMMER, Vina, fpocket and preprocessing through the selected Compute route
- [ ] 7.4 Execute authorized Batch 1 occurrences, same-attempt reconciliation, required negative tests, cleanup and budget settlement
- [ ] 7.5 Execute separately authorized AlphaFold Batch 2 minimal GPU inference and closure checks
- [ ] 7.6 Persist and independently verify exact real-subject receipts, leaving unresolved or failed units blocked and performing no adoption or cutover
- [ ] 7.7 Complete implementation evidence, sync specs and archive this change only after all authorized qualification scope is adjudicated

## 8. Cutover handoff gate

- [ ] 8.1 Stop after qualification and ask the operator to confirm deployment environment, maintenance window, migration, backup, rollback or forward-only boundary, monitoring, post-cutover smoke and final authorizer before creating `cut-over-enzymedesign-qualified-runtime`
