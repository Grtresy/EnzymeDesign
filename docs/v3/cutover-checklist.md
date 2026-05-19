# V3 Cutover Checklist

## Scope

This checklist covers the V3 product-surface cutover from the frozen V2 workflow path to the V3 harness-first path. The target surface is `/v3` API, V3 CLI/UI consumers, canonical control-plane projection, task board, lane isolation, delegation, approval, research, execution, report draft, and final report delivery.

## Entry Criteria

- `docs/v3/00-harness-doctrine.md` remains the governing boundary: top-level product truth is the harness control plane, not a workflow graph.
- `/v3` public API shape is frozen for this cutover window.
- V3 can create a session, accept a user message, create tasks, delegate to teammates, wake teammate runtime, run research and execution capabilities, create a report draft, publish a final report, and project the workspace.
- V3 execution can stage session artifacts into HPC `RunSpec.inputs`, fetch declared `expected_outputs`, and register fetched files as session artifacts.
- V3 execution can run an approved pipeline sandbox whose SDK performs required preprocess steps and supervised HPC calls for format-sensitive tools such as Vina.
- Runtime signal queue has durable claim leases, stale claim recovery, duplicate wakeup dedupe, and bounded scheduler drain coverage.
- Provider/tool limits cover agent/session/global concurrency, LLM provider calls, research provider calls, and execution/HPC submission calls.
- Design and deep-research production paths use no heuristic decision fallback: planner/model failures produce failed decisions or failed dossiers, tool argument validation is returned as a tool error observation, and unexpected runtime/provider exceptions are allowed to fail the gate.
- V2 continues to run for rollback only; no new product semantics are added to V2 during the cutover window.
- `docs/OpenZyme架构设计.md` is not changed as part of this cutover unless separately approved.

## Required Verification

- `uv run pytest -m "not integration" apps/openzyme-host-api packages/openzyme-core packages/openzyme-engines`
- `uv run python -m openzyme_host_api.evals --v3`
- `uv run pytest -m "integration and live_llm" apps/openzyme-host-api/tests -k v3`
- `uv run pytest -m "integration and live_tavily" apps/openzyme-host-api/tests packages/openzyme-research/tests`
- `uv run pytest -m "integration and live_hpc" apps/mcp-hpc-runner/tests apps/openzyme-host-api/tests`
- `uv run pytest -m "integration and live_e2e" apps/openzyme-host-api/tests`
- `cd apps/openzyme-web-ui && npm test && npm run build`
- `./scripts/check-mainline.sh`

## Eval Evidence

- Deterministic V3 E2E: `run_v3_local_evals()` must pass `v3_design_cutover_path`.
- Live LLM smoke: `run_v3_live_evals()` must pass `v3_live_design_task_plan` when live LLM tests are enabled.
- Seeded execution smoke tests that pre-create DB rows, patch UUIDs, or inject local fixture artifacts are useful regression evidence, but they do not satisfy the full `live_e2e` release gate.
- Full `live_e2e` evidence must run with real LLM, Tavily, and HPC configuration enabled. Missing configuration must be reported as missing gate prerequisites, not counted as a successful cutover result.
- Evidence must include task count, delegated teammate roles, capability keys, report count, and per-check pass/fail values.
- Execution evidence must include at least one pipeline invocation, one staged-input run, one multi-input run, one declared-output artifact fetch, and one preprocess-in-pipeline chain when Vina is enabled.
- Failed evals block cutover unless explicitly accepted as non-release-blocking by the owner.

## Observability Requirements

- V3 harness evals must be runnable with `--upload-results` to emit LangSmith workflow traces where configured.
- Session event replay must include conversation, task, tool, delegation, approval, engine, report draft, and report generation events.
- Session event replay/debug view must include diagnostic signal lifecycle events such as `signal.queued`, `signal.claimed`, `signal.completed`, and `signal.failed`.
- Session event replay must include execution pipeline lifecycle, preprocess completion, runner submission/status, output fetch, and artifact recording events for execution runs.
- `/debug/llm-calls` must remain available for local diagnosis of V3 harness and teammate LLM calls.
- Rollback diagnosis needs the session id, latest failing endpoint, event replay, pending approval ids, and LLM debug records.

## Cutover Steps

1. Freeze V2 feature changes and route all new product work to V3.
2. Run the required verification commands and attach the summaries to the release note or PR.
3. Enable V3 UI/CLI entry points for the cutover cohort.
4. Keep V2 endpoints and data available for rollback during the migration window.
5. Monitor V3 eval failures, live LLM tool-call failures, pending approval stalls, and report publishing failures.
6. After the migration window, follow `docs/v3/v2-retirement-plan.md`.

## Exit Criteria

- V3 deterministic eval and mainline checks pass.
- Live V3 task-plan, Tavily, HPC, and full live E2E gates pass in an environment with the corresponding provider configuration enabled.
- At least one full V3 workspace has a published final report projected through `/v3/sessions/{session_id}/workspace`.
- Rollback path has been rehearsed and documented in `docs/v3/rollback-strategy.md`.
