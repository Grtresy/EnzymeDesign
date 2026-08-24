# request-lineage-workflow-authority Specification

## Purpose
定义根消息、派生工作、下游唤醒与运行时执行所使用的精确工作流权威绑定、因果子集、生命周期和兼容失败语义。
## Requirements
### Requirement: Every root message creates an exact workflow authority binding
The Kernel SHALL resolve requested workflow refs against one Distribution-owned registry snapshot and atomically create `WorkflowAuthorityBinding@1` with the message, inbox, runtime signal and `RuntimeSignalAuthorityLink@1`. An explicit empty selection MUST create an active empty binding; missing metadata MUST NOT mean latest, all or default workflows.

#### Scenario: Admit an exact non-empty selection
- **WHEN** a user message requests valid versioned workflow refs
- **THEN** the resolver records their canonical ordered selection digest, registry snapshot digest, request lineage, actor, scope and epoch in the root binding and links the emitted signal

#### Scenario: Admit an explicit empty selection
- **WHEN** a user message requests no workflows
- **THEN** the Kernel records an active empty binding and the runtime receives no workflow authority beyond that empty selection

#### Scenario: Request an unknown workflow
- **WHEN** a message contains an unknown, ambiguous, historical-only or policy-denied workflow ref
- **THEN** admission fails before message/signal mutation with a stable safe error and no fallback selection

### Requirement: Derived workflow authority is a causal subset
Delegation to another Agent or narrower task/lane SHALL create a child binding whose selected refs and scope are a subset of the current active parent. The child MUST retain parent identity, derivation kind and causal source; prose, memory and unrelated current Session state MUST NOT add authority.

#### Scenario: Delegate an allowed subset
- **WHEN** `task.delegate` assigns work with a subset of the caller's workflows and scope
- **THEN** `ProtocolService.delegate()` atomically persists the delegation, child binding, recipient signal and exact signal link

#### Scenario: Delegate a wider selection
- **WHEN** a caller requests a workflow or scope absent from its active parent binding
- **THEN** delegation fails before inbox/signal/task-owner mutation and reports `workflow_authority_subset_violation`

#### Scenario: Text claims additional authority
- **WHEN** a task, protocol message, memory or assistant transcript says another workflow is authorized
- **THEN** the resolver ignores the text and revalidates only canonical binding records

### Requirement: Downstream wakeups preserve exact lineage authority
Protocol delivery, approval resolution, continuation delivery and other causal wakeups SHALL carry the exact current authority or an explicit derived child through `RuntimeSignalAuthorityLink@1`. Signals MUST NOT embed raw workflow refs as a substitute for the link.

#### Scenario: Resolve an approval
- **WHEN** a pending approval tied to a runtime occurrence is resolved
- **THEN** the scheduled continuation/wakeup signal links the same authority ID, epoch, digest and causation ref without executing the recipient synchronously

#### Scenario: Deliver a continuation
- **WHEN** an exact fenced continuation becomes ready
- **THEN** its new signal receives the source occurrence's current authority link and fails closed if the binding is no longer active

#### Scenario: Send a protocol message
- **WHEN** an Agent invokes `protocol.send`
- **THEN** only inbox and wakeup/link records are committed and the recipient is not run in the sender's request

### Requirement: Workflow authority revocation and execution are epoch fenced
Workflow bindings SHALL have a closed `active | revoked | expired | consumed` lifecycle with monotonic epoch and CAS-protected digest. Runtime admission, immediately before provider invocation, before each tool dispatch and before delegation settlement MUST revalidate the exact link and binding.

#### Scenario: Revoke after signal admission
- **WHEN** the binding epoch changes after a signal was enqueued but before provider invocation
- **THEN** the turn fails with a stale workflow authority observation and the provider is not called

#### Scenario: Revoke during a bounded turn
- **WHEN** the binding is revoked after a provider response but before a requested tool or delegation is dispatched
- **THEN** the dispatch is rejected without reopening, route switch or substitute workflow

#### Scenario: Receive a duplicate current link
- **WHEN** an idempotent command presents the same signal, authority, epoch and digest
- **THEN** the existing link is returned without creating a second lineage or widening selection

### Requirement: Workflow authority failure and compatibility are explicit
Workflow authority records SHALL be persisted with closed codecs and projected using public-safe identities. Legacy Sessions or signals that lack an exact current binding/link MUST fail closed; runtime MUST NOT reconstruct authority by scanning messages, selecting the latest registry entry or unioning related bindings.

#### Scenario: Restore a legacy signal without a link
- **WHEN** runtime admission observes a wakeup signal without `RuntimeSignalAuthorityLink@1`
- **THEN** it reports `workflow_authority_link_missing` and performs no provider/tool effect

#### Scenario: Restore a drifted registry snapshot
- **WHEN** the bound registry snapshot digest is unavailable or differs from the adopted Distribution snapshot
- **THEN** admission reports a structured compatibility failure and does not silently re-resolve against the new registry

#### Scenario: Inspect a private resolution failure
- **WHEN** workflow resolution raises an internal exception
- **THEN** the public record contains a stable error code and `diagnostic_id` while the private diagnostic retains the cause chain with `raise ... from exc`
