## MODIFIED Requirements

### Requirement: Runtime command status is session-scoped and bounded
The Host MUST expose `GET /v3/sessions/{session_id}/runtime/commands/{command_id}` for the current command state and bounded outcome summary. The command MUST belong to the requested session. A runtime command MUST become terminal when its bounded scheduler batch finishes, fails, locks, or parks work; a parked controlled operation MUST continue under execution/continuation ownership rather than extending command lifetime. For new command outcomes, the bounded summary MUST separately preserve authoritative scheduler status, the actual processed signal count, suspension, post-scheduler projection status, and whether command replay is safe. A projection, event-enrichment, or workspace failure after scheduler progress MUST NOT replace the actual processed count with zero or imply that the scheduler batch did not happen.

#### Scenario: Poll an accepted command
- **WHEN** a caller polls a valid command id in its owning session
- **THEN** the Host returns one of the closed command states with bounded scheduler and projection outcome facts and no private worker authority

#### Scenario: Reject a cross-session command lookup
- **WHEN** a caller uses a valid command id under another session path
- **THEN** the Host rejects or hides the command without disclosing its owning session

#### Scenario: Finish a command on suspension
- **WHEN** the bounded agent batch parks a tool invocation on approval or external work
- **THEN** the runtime command terminates with a suspension summary while the controlled-operation execution remains independently nonterminal

#### Scenario: Projection fails after one signal was processed
- **WHEN** the scheduler durably processes one signal and a required consistency/event/workspace projection then fails
- **THEN** the command terminates with the actual processed count of one, `projection_status=failed`, a stable projection error, and `replay_safe=false`

#### Scenario: Executor fails before scheduler progress exists
- **WHEN** the runtime command executor fails before it can form an authoritative scheduler receipt
- **THEN** the command may report zero processed signals but MUST distinguish that boundary failure from a post-progress projection failure

#### Scenario: Read a historical command outcome
- **WHEN** a caller polls a command stored under the prior bounded outcome schema
- **THEN** the Host preserves and safely projects its original fields without inventing new scheduler or projection facts

## ADDED Requirements

### Requirement: Runtime drain preserves a core receipt across projection settlement
The runtime drain implementation SHALL form an immutable internal core receipt immediately after the bounded scheduler batch, before trace/activity/consistency enrichment, event append, or composite workspace construction. Post-scheduler settlement SHALL produce a separate typed projection outcome. A worker catch-all MUST NOT overwrite a core receipt that has already been formed.

#### Scenario: Complete scheduler and projection
- **WHEN** the scheduler batch and every required projection settlement complete
- **THEN** the terminal command records both layers as complete with the exact processed signal count

#### Scenario: Fail consistency projection after max steps
- **WHEN** a teammate turn exhausts its budget, its signal/failure facts are durable, and scientific consistency projection then fails
- **THEN** the command preserves the processed signal and teammate outcome, records projection failure separately, and forbids blind command replay

#### Scenario: Do not swallow a programming error
- **WHEN** an unexpected projection exception occurs after a core receipt exists
- **THEN** the Host exposes a sanitized typed failure while retaining progress facts rather than silently returning successful projection status

#### Scenario: Aggregate Core-owned settlement facts
- **WHEN** the scheduler returns typed outcome settlements and releases its session runtime lease
- **THEN** core receipt assembly consumes those immutable settlements without rescanning mutable task, signal, failure, agent, or wakeup repositories

#### Scenario: Keep business exit separate from scheduler settlement
- **WHEN** an agent explicitly finishes a task as completed, blocked, failed, or cancelled and its source signal settles successfully
- **THEN** the scheduler layer reports the bounded signal/batch settlement independently from that business task status

### Requirement: Step-budget exhaustion is recoverable runtime attention
When a bounded agent turn exhausts its configured step budget without an explicit terminal task action, the exact turn and source signal SHALL terminate without automatic replay, while the business task remains nonterminal. The canonical failure observation MUST use a stable budget-exhaustion code, identify that the agent can replan, and keep exact-signal retry eligibility separate from task/agent recoverability.

#### Scenario: Teammate exhausts its budget
- **WHEN** a teammate reaches max steps with no `task.finish` and no recovered terminal outcome
- **THEN** its exact signal becomes terminal failed, the observation records `agent_can_replan`, and the task retains its prior nonterminal status and business failure fields

#### Scenario: Do not replay the same signal
- **WHEN** max-step recovery attention is projected
- **THEN** the runtime does not reset or replay the terminal signal, increase its budget, reopen an operation, or continue a scientific attempt automatically

#### Scenario: Wake master with canonical recovery facts
- **WHEN** a teammate max-step outcome becomes durable
- **THEN** one source-bound deduplicated master wakeup can inspect the failure and current scientific selection evaluation before the master chooses resume, redelegation, help, blocked, failed, or another strategy

#### Scenario: Settle a closed teammate budget handoff
- **WHEN** a teammate max-step outcome has one canonical terminal signal, the exact structured budget observation, a nonterminal business task, and exactly one source-bound pending master wakeup
- **THEN** the signal remains failed and unreplayed while the scheduler batch may report completed settlement, so a later bounded command can claim only the new master turn

#### Scenario: Form one typed budget handoff snapshot
- **WHEN** the runtime terminalizes a teammate max-step occurrence and durably creates its exact observation and successor wakeup
- **THEN** Core forms one immutable typed settlement under the same session runtime authority, binding the source occurrence, task/agent/lane/correlation snapshot, failure identity, successor identity, and batch-barrier disposition

#### Scenario: Stop the batch before claiming the successor
- **WHEN** any claimed agent occurrence exhausts its step budget while `max_signals` still permits more work
- **THEN** the scheduler finishes already claimed work in the current wave, stops that bounded batch, and does not claim a successor signal created by the exhausted occurrence until a later command or background tick

#### Scenario: Preserve the handoff result after later progress
- **WHEN** a later authorized turn claims or completes the successor and may change the business task
- **THEN** that later state does not retroactively change the immutable settlement of the source occurrence or force Host receipt reclassification

#### Scenario: Keep an incomplete budget handoff failed
- **WHEN** the budget observation, nonterminal task boundary, or unique source-bound master wakeup is missing, mismatched, duplicated, or cancelled
- **THEN** the scheduler batch remains failed and MUST NOT relabel the signal occurrence as settled, while max-step still ends the current batch before any candidate successor is claimed

#### Scenario: Do not invent a successor for master exhaustion
- **WHEN** the master signal itself exhausts max steps
- **THEN** that signal and scheduler batch remain failed unless another independently authorized canonical signal already exists; the runtime does not manufacture a self-wakeup

#### Scenario: Preserve controlled effects from the exhausted turn
- **WHEN** the exhausted turn already produced controlled-operation effects
- **THEN** the signal failure's no-effect classification does not erase, downgrade, replay, or reinterpret those operations' independent effect certainty and durable results

### Requirement: Runtime consistency uses structured failure and resolved selection facts
Runtime consistency projection SHALL classify new max-step outcomes from canonical failure observation codes and SHALL inspect scientific selection lifecycle through the resolved head/readiness model. Legacy error-text matching MAY remain read-only compatibility, but new outcomes MUST NOT depend on free-text parsing.

#### Scenario: Audit a draft scientific head after max steps
- **WHEN** a nonterminal task has a failed budget-exhausted signal and a valid draft scientific selection head
- **THEN** consistency returns agent-turn attention and draft selection facts without raising or claiming a sealed-unclosed selection

#### Scenario: Audit a sealed unclosed selection
- **WHEN** the resolved current selection is sealed and no exact attempt closure exists
- **THEN** consistency emits `scientific_selection_sealed_unclosed` using the canonical selection state

#### Scenario: Audit an invalid selection head
- **WHEN** head resolution detects missing or mismatched canonical selection identity
- **THEN** consistency emits a bounded `scientific_selection_head_invalid` integrity warning and leaves the task business status unchanged
