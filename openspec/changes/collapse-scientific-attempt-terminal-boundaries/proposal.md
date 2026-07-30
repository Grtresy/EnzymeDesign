## Why

r62 reproduced the r58 failure class after all scientific operations, task exits, and report publication had succeeded: the canonical attempt owner was forbidden to close its own attempt, the resident master omitted the duplicated close, and supervision converted an open lifecycle with no wake source into 120 empty drains and a fact-erasing wrapper failure. The durable fix is to remove the cross-role/co-terminal machinery and make one canonical scientific lifecycle owner converge independently from report and conversation delivery.

## What Changes

- **BREAKING** Make the assignee of the scientific attempt's canonical task the only agent-facing closure requester; AOX no longer requires the resident master, an exact three-task board, reporter identity, report publication, or final-response text before accepting a closure request.
- **BREAKING** Require a scientific attempt task to have an immutable closure before `task.finish(status=completed)` can terminate that task. Closure remains agent-authored, Host-finalized after writer retirement, and never implies task completion.
- **BREAKING** Remove the active co-terminal closure-response domain object, repository, conversation transaction, tool/harness plumbing, and no-model response-binding settlement. Historical migration/table bytes remain readable for frozen evidence only.
- Treat `scientific.attempt.closed` as a real source-bound lifecycle event that may wake the still-open attempt task through the ordinary fenced runtime path; do not add a synthetic wakeup, hidden fallback, automatic task finish, or response veto.
- Collapse live coordination onto canonical lifecycle plus existing writer/process retirement facts. A completed product projection with an open attempt and no eligible wake source fails after two identical replay-safe empty observations with the earliest typed cause rather than exhausting the drain bound.
- Preserve original operation, task, report, MICU, authority, effect, and process observations through supervision and decision wrappers; attestation failure no longer rewrites completed operations as failed.
- Stop durably amplifying identical derived runtime-consistency warnings on every command while retaining the read-only consistency projection.
- Replace the sealed-source arbitrary absolute-path syntax matcher with explicit secret/private-root/private-locator controls so ordinary source syntax such as `#!/usr/bin/env python3` remains attestable.
- Update the active AOX blank-world change and V3 architecture documents so historical r58-r62 evidence remains factual while the current contract no longer prescribes master-owned co-terminal closure.

## Capabilities

### New Capabilities

- `sealed-source-evidence-safety`: Defines source-evidence publication and attestation rules that preserve exact source bytes and digests while rejecting actual secrets, private roots, private locators, and path escapes without interpreting arbitrary language syntax as a Host path.

### Modified Capabilities

- `scientific-attempt-terminal-rollover`: Moves closure request ownership to the canonical attempt task assignee, orders immutable closure before explicit task completion, and keeps Host quiescence/fencing as the sole finalization authority.
- `scientific-closure-notification-settlement`: Replaces co-terminal response-bound mechanical settlement with an ordinary fenced lifecycle notification that can wake the still-open attempt task without inferring completion or producing a response.
- `live-attempt-supervision`: Requires bounded no-wakeup classification and lossless preservation of the earliest typed product/effect facts instead of drain exhaustion or outer-wrapper replacement.

## Impact

- Affected packages: `openzyme-domain`, `openzyme-runtime`, `openzyme-core`.
- Affected Host paths: AOX tool policy, runtime observation/driver, attempt supervision, evidence sealing, decision projection, and V3 runtime consistency events.
- Active SQLite schema remains forward compatible: migration 035 and historical closure-response rows are retained, but current runtime stops creating or requiring them.
- Public/runtime contracts and tests change around `scientific.attempt.close`, `task.finish`, closure notification, live diagnostic evidence, and sealed source trees.
- `docs/OpenZyme架构设计.md`, stable `docs/v3/`, the active AOX OpenSpec, and historical-session annotations require synchronization.
- No live r-series, provider, MICU, HPC, or browser action is authorized by this change.
