# Requirements to Tests and Evidence Matrix

Date: 2026-07-29

This matrix describes repository/operator evidence only. Test-gate plans,
diagnostic receipts, replay receipts, benchmark samples, and mainline receipts
do not satisfy architecture admission, AOX launch, live-campaign, or scientific
evidence contracts.

## Nineteen requirements

| # | Requirement | Primary implementation/tests | Current evidence |
| ---: | --- | --- | --- |
| 1 | Diagnostic profiles are permanently non-authoritative | `test_test_gate_config.py::test_config_rejects_any_authority_upgrade_for_diagnostics`; `test_test_gate_diagnostic.py::test_diagnostic_verifier_rejects_authority_upgrade_and_missing_stage` | focused/affected/replay receipts fix `authoritative=false`, `admission_eligible=false`, `live_eligible=false` |
| 2 | Focused selection is explicit, bounded, and closed | `test_test_gate_diagnostic.py::test_focused_selection_is_explicit_deduplicated_and_closed`; parameterized invalid-input test | Phase 1 focused Core/Host/architecture samples |
| 3 | Affected scope binds the complete local change inventory | `test_test_gate_affected.py::test_change_inventory_combines_committed_staged_unstaged_and_untracked`; map coverage test | `phase1-diagnostic-results.md` |
| 4 | Unknown impact expands instead of omitting work | `test_test_gate_affected.py::test_unknown_and_conflicting_paths_expand_to_complete_safe_set`; map-drift test | complete-safe fallback receipt cases |
| 5 | Frontend diagnostic omission is explicit and dependency-tested | `test_test_gate_affected.py::test_public_projection_and_ui_changes_include_frontend_contracts`; public-shape parameterization; owner-local omission test | frontend inclusion/omission rows in `phase1-diagnostic-results.md` |
| 6 | Diagnostic collection and execution cannot trigger live effects | `test_test_gate_diagnostic.py::test_diagnostic_effect_guard_blocks_remote_network_and_collection_processes`; credential/environment tests | closed non-live environment and effect-guard receipts |
| 7 | Diagnostic receipts explain selection and limitations | focused/affected execution and verifier tests in `test_test_gate_diagnostic.py` | pure-verified plan/receipt bundles |
| 8 | Diagnostic latency targets are measured without shrinking selection | `test_test_gate_benchmark.py`; selection-closure tests | representative 10–60 second assessment in `phase1-diagnostic-results.md` |
| 9 | Authoritative mainline preserves the complete non-live gate | `test_test_gate_contract.py`; `test_shadow_plan_closes_obligations_owners_and_exact_manifest` | post-cutover fixed-four and forced-serial receipts each close 2,817/2,817/2,817 exact nodes, qualification 84+13, and both frontend commands; historical 2,801-node parity and 2,808-node five-pair closure remain source-bound inputs |
| 10 | Execution planning binds exact source and environment identity | `test_test_gate_source.py`; `test_plan_rejects_marker_source_config_and_environment_drift`; source rechecks | every plan/sample/receipt carries source/toolchain/environment digests |
| 11 | Every required pytest node has one closed owner | shadow missing/duplicate-owner test; plan owner verifier tests | `G/Qh/Qs` shadow closure and exact ownership manifests |
| 12 | Qualification deduplication remains exact and same-invocation only | qualification-sidecar tests; `test_same_invocation_qualification_sidecar_closes_qh_qs_and_report`; qualification fail/timeout tests | 84 harness + 13 scenario nodes owned once; same-source legacy outcome parity |
| 13 | Compatibility audit uses one semantic repository inventory | `test_compat_caller_audit.py`; semantic CLI parity; reader-count and adversarial fixtures | `phase1-audit-results.md` |
| 14 | Stage order and terminal semantics remain deterministic | fail-fast, timeout, dependency, and stage-attribution tests | exact seven-stage plan and receipt order |
| 15 | Timing and baseline evidence are source-bound and statistically closed | `test_test_gate_benchmark.py`; legacy/optimized sample reducers | final five-pair cold/warm medians show 39.94% / 40.17% reduction and 2.202% maximum orchestration overhead |
| 16 | Parallel execution requires exact resource-isolation proof | `test_test_gate_resource.py`; fixed-xdist plugin tests | 1,292 audited nodes; fixed 2/3/4, reverse, shuffled, and forced-serial comparisons |
| 17 | Authoritative receipts prove closure without becoming product truth | authoritative receipt verifier tests; `test_mainline_receipt_has_no_product_or_scientific_consumer` | pure offline verification and consumer rejection |
| 18 | Authority cutover and rollback are explicit | `test_authority_modes_have_distinct_files_commands_and_verifier_domains`; `test_authoritative_receipt_requires_the_authoritative_verifier_domain`; optimized/frozen wrapper contract tests | the user agreed to the immutable twenty-case corpus; replay and five-pair thresholds closed; `scripts/check-mainline.sh` is now the sole current authority, `--forced-serial` preserves the contract, and `scripts/check-mainline-legacy.sh` is explicitly non-authoritative |
| 19 | Serial hotspot optimization preserves tested behavior | `test_migrations.py`; test-gate parity/resource tests | atomic fresh SQLite initialization, rollback fault, current critical-path report |

## Failure-injection closure

| Boundary | Injected failures | Proof tests |
| --- | --- | --- |
| Canonical evidence | duplicate JSON keys, unknown schema/field, non-finite value, digest tamper, noncanonical alias | `test_test_gate_model.py` |
| Output/process runner | relative/in-checkout/existing output root, no-replace collision, bounded tail, TERM retirement, SIGKILL escalation | `test_test_gate_runner.py` |
| Source identity | tracked/staged/unstaged/relevant-untracked drift, untracked symlink, configuration/lock/toolchain drift | `test_test_gate_source.py`; authoritative source-drift tests |
| Legacy benchmark | command failure, source drift despite process pass, fewer than five pairs, source/host mismatch | `test_test_gate_benchmark.py` |
| Shadow coverage | missing owner, duplicate owner, collection drift, forbidden marker, malformed/prior observation, source/environment drift | `test_test_gate_shadow.py` |
| Planner | qualification node outside `G`, owner/command/dependency/worker drift, marker/config/environment drift, stale resource identity | `test_test_gate_authoritative.py` |
| Qualification | missing/mismatched sidecar, fail, timeout, report mismatch, source/environment drift, harness/scenario drift, skip/xfail unproven, attempted ordinary-pytest fallback | qualification section of `test_test_gate_authoritative.py`; architecture-qualification runner/report tests |
| General selection | manifest mismatch, prior plan, unexpected deselection, policy deselection drift, duplicate/missing node | `test_test_gate_pytest_plugin.py`; authoritative manifest/receipt tests |
| Resource isolation | stale digest, new node, missing proof, invalid or `auto` worker count, missing xdist, allocation failure, worker crash, unknown result, leaked process, forbidden shared path/env/cwd/signal/socket resource | `test_test_gate_resource.py`; fixed-xdist plugin test |
| Receipt verification | missing stage, unknown schema, digest drift, source drift, missing/duplicate result, unexpected deselection, missing frontend, prior invocation, worker failure, timeout, shadow/authority domain crossing | receipt fault parameterizations and authority-domain tests in `test_test_gate_authoritative.py` |
| Diagnostic selection | empty/external/traversal/missing/unknown/live selector, invalid base, map drift, forbidden effect during collection, source drift, unexpected deselection, authority upgrade | `test_test_gate_affected.py`; `test_test_gate_diagnostic.py` |
| Compatibility audit | unreadable/invalid Python or TOML, retired caller, active seam implementation loss, documentation/non-Python literal drift, ordering instability | `test_compat_caller_audit.py` |
| Migration/schema | invalid fresh migration inside atomic transaction, partial schema/user-version persistence, open transaction, foreign-key state loss | `test_migrations.py::test_fresh_sqlite_initialization_is_atomic_on_migration_failure` |
| Replay corpus | case count/order drift, open green projection, missing proof node, duplicate proof node, digest tamper | `test_test_gate_replay.py` |
| Product/live boundary | diagnostic/mainline receipt presented to architecture admission, AOX, live campaign, or scientific consumer | `test_test_gate_contract.py::test_mainline_receipt_has_no_product_or_scientific_consumer`; authoritative consumer tests |

The independent positive boundary is recorded in
`architecture-admission-independence-evidence.md`: an exact disposable clean
candidate ran full admission, separate pure verification, and the existing AOX
receipt consumer without a mainline plan/sidecar/receipt and with
`external_effects_real=false`.

## Mandatory command and authority closure

- Mainline always contains both `web_ui_test` (`npm test`) and
  `web_ui_build` (`npm run build`); a missing or non-pass frontend result makes
  the receipt fail.
- The authoritative marker expression excludes `integration`, all configured
  `live_*` markers, `seeded_live_smoke`, and `quality_eval`. Ambient
  credentials or `PYTEST_ADDOPTS` cannot activate them.
- `premerge_subset` remains the exact qualification mode. It is stricter owner
  evidence inside mainline but is never architecture-admission evidence.
- Replay corpus digest
  `sha256:136cacea60eb8022fbe58672c0c4801545a381cb00343c455c7a2406f898d202`
  binds exactly twenty current proof nodes. Its execution is a
  `focused_diagnostic` receipt and is permanently non-authoritative.
- Cutover is not inferred from this matrix alone. It is closed independently by
  the explicit replay-corpus agreement, the twenty-case replay receipt, the
  final same-source five-pair threshold, the optimized and forced-serial
  authority receipts, the labeled rollback wrapper, and the clean architecture
  admission evidence. Their raw paths and digests are recorded in
  `replay-corpus-evidence.md`, `phase9-critical-path.md`,
  `authority-cutover-evidence.md`, and
  `architecture-admission-independence-evidence.md`.
