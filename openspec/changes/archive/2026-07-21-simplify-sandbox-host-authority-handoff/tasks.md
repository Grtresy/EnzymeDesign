## 1. Typed Host authority boundary

- [x] 1.1 Add immutable session-turn, sandbox-process, durable-execution, and continuation-delivery authority records with fail-closed identity validation.
- [x] 1.2 Add `SandboxHostCallContext`, typed context/mutation-writer factories, and the `SandboxHostGateway` protocol using `CoreRepositories` instead of `Any`.
- [x] 1.3 Add unit tests for valid owner contexts, mixed-owner rejection, session mismatch, execution mismatch, and mutation-writer derivation.

## 2. Composition-root and engine migration

- [x] 2.1 Implement the execution-engine Host gateway so adapter execution and HPC fetch always bind to an explicit call context.
- [x] 2.2 Migrate `_ControlSocketServer`, `SandboxRuntimeService`, tool registration, and teammate registry wiring from reflected callbacks and dual repository factories to the typed gateway/context factory.
- [x] 2.3 Migrate the Host API composition root and legacy pipeline callback path to construct explicit session-turn or sandbox-process contexts without leaking the originating lease.
- [x] 2.4 Migrate durable provider/HPC route adapters to durable-execution contexts and remove the callback-scope rebinding helper.
- [x] 2.5 Remove `SandboxHpcFetchExecutor`, `Callable[..., ...]`, `sandbox_process_repository_scope_factory`, and the optional `repositories: Any | None` fetch override; add a repository-wide regression assertion for the removed weak path.

## 3. Lifecycle and authority fault coverage

- [x] 3.1 Add a file-backed composition-root test covering agent lease acquisition, sandbox park, lease release, durable execution, continuation delivery, and a subsequent same-process `hpc.fetch_outputs` call.
- [x] 3.2 Add negative tests proving stale session, stale execution, stale continuation delivery, mismatched process epoch, and frozen mutation-writer authority each fail at their own boundary.
- [x] 3.3 Verify the post-delivery fetch publishes only declared outputs, does not redispatch the external effect, and does not change business task terminal state.

## 4. Bounded runtime barrier and AOX driver cleanup

- [x] 4.1 Implement a closed, bounded, read-only runtime barrier projection over existing canonical repositories with no persistence or authority acquisition.
- [x] 4.2 Add projection tests for active suspension, active writers, locked/active runtime work, settled state, bounds, and repeated-read non-mutation.
- [x] 4.3 Split AOX runtime observation into a focused module that consumes the barrier projection while leaving deadlines/evidence orchestration in the campaign driver.
- [x] 4.4 Delete the replaced `_task_has_active_durable_suspension`, `_session_has_inflight_mutation_writers`, and `_session_state` direct database helpers and migrate their tests.

## 5. Documentation and proposal lifecycle

- [x] 5.1 Update `docs/OpenZyme架构设计.md` and relevant `docs/v3/` runtime/execution documents to describe the four Host-call owner authorities plus mutation-writer boundary and post-continuation behavior consistently.
- [x] 5.2 Add an architecture-proposal lifecycle index and umbrella relationships without merging unrelated proposals; mark implemented, superseded, deferred, and active documents explicitly.
- [x] 5.3 Record r41-r44 chronology, mark earlier re-entry GO claims as superseded by later live facts, and document that numbered live campaign admission remains paused.
- [x] 5.4 Define and document the archive convention that moves a completed architecture proposal beside its completed OpenSpec change while preserving stable traceability links.

## 6. Verification and archive

- [x] 6.1 Run typed-boundary, sandbox lifecycle, durable-route, runtime-barrier, AOX driver, and authority fault-matrix focused tests.
- [x] 6.2 Run Ruff, the non-live mainline suite, and strict OpenSpec validation; fix all in-scope failures.
- [x] 6.3 Verify implementation, specs, design, docs, and task checkboxes agree, then archive this completed change together with its completed authority-handoff proposal.
