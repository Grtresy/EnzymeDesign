# openzyme-runtime-adapter Specification

## Purpose
定义独立 Runtime SPI、canonical runtime command/outcome、lease/fence 消费以及可替换 LLM 与 process Adapter 边界。
## Requirements
### Requirement: Runtime SPI is independent from runtime implementations
`openzyme-runtime-spi` MUST define only AgentRuntimeAdapter, closed runtime command/outcome/failure DTOs and capability gateway ports, and MUST depend only on `openzyme-contracts`. It MUST NOT import LangChain, model/provider SDKs, prompt implementations, Research or process/container mechanisms.

#### Scenario: Install and import the SPI alone
- **WHEN** a fresh environment installs the SPI wheel without any runtime implementation extra
- **THEN** it imports successfully and a deterministic fake adapter can implement every required protocol

#### Scenario: Framework object crosses the SPI
- **WHEN** a command, outcome or public adapter method exposes a LangChain message, runnable, provider response or process handle
- **THEN** contract and wheel qualification fail before release

### Requirement: Runtime commands bind exact canonical coordination identity
Every RuntimeTurnCommand MUST bind the Session, Agent member, claimed signal occurrence, Task/Lane focus when present, SessionRuntimeLease generation/fence, process epoch, continuation identity, bounded step/time/budget, pinned Distribution/Extension/declared-tool identities, SessionCapabilityBindingRevision and exact ToolAffordanceSnapshot digest. An Adapter MUST treat the command as immutable.

#### Scenario: Execute a current command
- **WHEN** all command identities match the active Session and runtime lease
- **THEN** the adapter receives one bounded command and only the capability gateway authorized for that command

#### Scenario: Catalog or affordance drifts before execution
- **WHEN** the command's Distribution/Extension/declared-tool digest differs from the Session pin or its affordance snapshot no longer revalidates
- **THEN** execution is rejected before an LLM, process or tool call and no replacement command is synthesized

### Requirement: Runtime outcomes are closed proposals rather than canonical writes
RuntimeTurnOutcome MUST be a closed DTO containing only model-visible messages/tool requests, bounded usage, safe summary, continuation/settlement proposal and structured failure. The adapter MUST NOT write repositories, complete Tasks, mutate Protocol, extend leases or dispatch an external operation directly.

#### Scenario: Adapter returns a tool request
- **WHEN** a valid outcome requests an authorized tool
- **THEN** the Kernel validates the call identity, schema, lease, approval and catalog before any invocation is admitted

#### Scenario: Adapter tries to return task terminal state
- **WHEN** an implementation includes an undeclared Task status mutation in its outcome
- **THEN** closed-schema validation rejects the entire outcome and the Task remains unchanged

### Requirement: Outcome consumption is lease and fence protected
The Kernel MUST accept an outcome only once for the exact live command, signal claim, runtime lease generation/fence and process epoch. Duplicate, stale, cross-Session or wrong-member outcomes MUST have no canonical effect and MUST NOT consume or replace the current command.

#### Scenario: Late process returns after retirement
- **WHEN** a retired runtime process returns an otherwise well-formed outcome under its old epoch
- **THEN** the Kernel rejects it as stale, preserves current owner state and records the old command/epoch identity

#### Scenario: Duplicate outcome is delivered
- **WHEN** the same exact settled outcome is delivered again
- **THEN** idempotent observation returns the prior settlement without reapplying messages, tools, events or continuation delivery

### Requirement: LLM and provider behavior belongs to a replaceable adapter
Model selection, Provider client construction, prompt/context assembly, compaction, token/model limits, connectivity diagnostics and framework middleware MUST live in `openzyme-runtime-llm` or a peer runtime implementation. Replacing that implementation MUST NOT change Session, Task, authority, revision, operation or runtime coordination schema.

#### Scenario: Replace the model provider
- **WHEN** composition selects another conforming LLM runtime adapter for new Sessions
- **THEN** Kernel DTOs and state transitions remain unchanged and the adapter identity is reflected only in the pinned implementation/composition identity

#### Scenario: Provider fails
- **WHEN** the selected Provider raises or returns an invalid response
- **THEN** the adapter emits a structured failure and does not silently choose another model, rewrite the prompt intent or report a successful turn

### Requirement: Process isolation belongs to a replaceable process Adapter
Subprocess, Podman/capsule image, environment/mount construction, process supervision, bounded stdout/stderr and process retirement MUST live outside Kernel behind an explicit ProcessIsolationPort Adapter such as `openzyme-process-podman`. The Adapter MUST enforce the exact command workspace generation, AgentAuthorityLease and process epoch supplied by coordination.

#### Scenario: Launch an isolated runtime process
- **WHEN** a valid runtime command requires process isolation
- **THEN** the process adapter launches only the declared image/argv/environment/mount set and returns a typed process identity without exposing a mutable Host path to the Agent contract

#### Scenario: Process outlives its lease
- **WHEN** the runtime lease expires or the member retires while a process remains
- **THEN** the process adapter performs bounded retirement and any later result is fenced from canonical mutation

### Requirement: Runtime failure observations preserve cause and effect facts
Runtime and process adapters MUST map failures to the common FailureObservation envelope with stable code, component, phase, correlation identities, effect certainty, mutation/fallback facts, retry/reconcile policy, diagnostic ID and chained private cause. Public results MUST be bounded and secret-safe.

#### Scenario: Process exits nonzero
- **WHEN** a process adapter observes a nonzero exit with stdout and stderr
- **THEN** the public failure contains the exit phase and safe bounded facts while protected diagnostics retain return code and bounded streams under the same diagnostic ID

#### Scenario: Adapter cannot determine an effect
- **WHEN** a runtime-mediated external invocation may have occurred but no receipt is available
- **THEN** the failure preserves unknown effect certainty and instructs reconciliation rather than authorizing an automatic retry

#### Scenario: Mounted tool runtime raises a typed effect failure
- **WHEN** a mounted runtime raises a closed failure carrying code, effect certainty, mutation fact, diagnostic identity and reconciliation policy
- **THEN** the gateway preserves those exact safe facts and does not replace them with a generic certainty or retry policy

#### Scenario: Mounted tool runtime raises an unclassified exception after invocation starts
- **WHEN** the gateway cannot prove whether the invoked runtime crossed its effect boundary
- **THEN** it reports `dispatch_in_doubt`, `mutation_applied=null`, `reconcile_required=true` and `fallback_performed=false`

### Requirement: Runtime completion remains separate from continuation and Task completion
An adapter turn ending, a process exiting, an outcome being consumed and a continuation being delivered MUST remain distinct state transitions. None of them alone MAY imply Task completion, scientific closure, report publication or controlled-operation success.

#### Scenario: Continuation is delivered after a capability outcome
- **WHEN** a terminal capability outcome wakes its owning Agent and the continuation is consumed
- **THEN** runtime delivery facts settle while the Agent retains the decision whether to call `task.finish` or take another action

#### Scenario: Bounded turn reaches its step limit
- **WHEN** the adapter returns a valid step-limit outcome
- **THEN** the signal/command settles according to runtime policy, the Task remains non-terminal and no hidden follow-up turn is enqueued unless an explicit canonical wake fact requires it

### Requirement: Runtime commands carry a closed structured world context
`runtime_turn_command@2` SHALL carry an exact `RuntimeTurnContext@1` plus workflow authority and tool exposure identities. The Adapter MUST treat this context as immutable input and MUST NOT query canonical repositories or manufacture missing collaboration truth.

#### Scenario: Run a current structured turn
- **WHEN** command, context, workflow binding, affordance and exposure digests all match current Kernel state
- **THEN** the Adapter presents the structured constraints and bounded transcript to the selected provider

#### Scenario: Context identity drifts
- **WHEN** the command's context digest or linked authority/exposure identity differs from the admitted occurrence
- **THEN** execution fails before the provider is invoked

#### Scenario: Old command lacks structured context
- **WHEN** a legacy `runtime_turn_command@1` is presented to the current Adapter
- **THEN** it is rejected as incompatible rather than reconstructed from recent messages

### Requirement: Provider input preserves current constraints under bounded compaction
The LLM Adapter MAY deterministically compact historical conversation to fit the immutable input budget, but MUST retain current Session objective, Task/lane/workspace, inbox/approval/failure, workflow authority, capability/exposure and fence identities. Compaction summaries MUST be historical and authority-free.

#### Scenario: Transcript exceeds the input budget
- **WHEN** historical user/assistant/tool messages exceed the command budget
- **THEN** the Adapter keeps all current structured constraint facts and emits an explicit deterministic historical-compaction marker

#### Scenario: Current authority alone exceeds the bound
- **WHEN** non-droppable current facts cannot fit the admitted input budget
- **THEN** the turn fails with a bounded-context error and the provider is not called

### Requirement: Deferred tool expansion is visible on the next provider step only
The Adapter SHALL request the current model-visible tool list before every provider step. A successful exact `capabilities.inspect` expansion MAY add Deferred tools for later steps of the same command, but MUST NOT carry the expansion across commands or bypass dispatch revalidation.

#### Scenario: Inspect then expand a Deferred tool
- **WHEN** the model inspects and explicitly expands one available Deferred tool
- **THEN** that tool appears in the next provider step while its authority, approval, route and health remain unchanged

#### Scenario: Attempt to expand a Hidden tool
- **WHEN** a model supplies a Hidden or unknown tool name to inspection
- **THEN** the result does not disclose or expose the tool and no expansion state changes

#### Scenario: Resume in a new command
- **WHEN** a continuation starts another runtime command
- **THEN** exposure is recomputed from the new role policy and no prior ephemeral expansion is inherited

### Requirement: Runtime outcomes preserve full transcript and typed failure proposals
The Adapter SHALL return every emitted assistant/tool message, tool request, usage fact, disposition and optional `FailureObservation` in one closed `RuntimeTurnOutcome`. It MUST NOT write canonical transcript, Task, approval or continuation state directly.

#### Scenario: Provider returns an assistant reply
- **WHEN** the selected provider returns content without a tool call
- **THEN** the outcome contains a stable assistant message identity and remains a proposal until Kernel settlement

#### Scenario: A tool returns a structured error
- **WHEN** a mounted tool rejects invalid arguments or current authority
- **THEN** the Adapter appends the exact tool result to the outcome and lets the model replan within the existing bounds

#### Scenario: Provider fails
- **WHEN** the explicitly selected provider exhausts its documented retry policy or reports a terminal failure
- **THEN** the outcome contains a public-safe canonical failure with effect/mutation/fallback facts and no provider substitution

### Requirement: Runtime execution revalidates workflow authority before effects
The runtime owner SHALL revalidate the exact workflow authority link immediately before provider invocation, and the capability gateway SHALL revalidate it before every tool or delegation dispatch. A stale epoch MUST terminate or reject the occurrence without hidden successor work.

#### Scenario: Authority changes before provider call
- **WHEN** admission succeeded but the binding epoch changes before `run_turn`
- **THEN** provider invocation is skipped and a stale-authority failure is settled

#### Scenario: Authority changes between model steps
- **WHEN** authority is revoked after one no-effect inspection and before a mutating tool call
- **THEN** the mutating call is rejected and no replacement workflow or route is selected
