## ADDED Requirements

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
