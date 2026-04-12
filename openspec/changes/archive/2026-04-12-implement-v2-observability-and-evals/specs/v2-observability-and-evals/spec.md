## ADDED Requirements

### Requirement: V2 workflow execution can emit LangSmith traces with episode-scoped metadata
The system MUST support LangSmith tracing for V2 workflow execution and Host entrypoints in a way that preserves episode-level audit context.

The initial tracing support MUST include at least:

- traceability for Host-triggered workflow execution
- traceability for supervisor or subgraph execution paths
- metadata or tags that can identify the relevant project, episode, and workflow phase

#### Scenario: Host-triggered workflow run is traced
- **WHEN** a traced workflow execution is started through the Host
- **THEN** LangSmith receives a trace for the workflow execution path
- **THEN** the trace can be correlated back to the project or episode that produced it

### Requirement: Observability supports request-to-workflow trace continuity
The system MUST support trace continuity across the main request boundary so Host request context can be associated with downstream workflow execution.

The initial continuity model MUST support at least:

- preserving trace context from Host entrypoints into workflow invocation
- associating approval or resume actions with the episode-scoped workflow they continue

#### Scenario: Resume action is correlated with downstream workflow execution
- **WHEN** a user resumes or approves an episode through a traced Host request
- **THEN** the resulting workflow execution can be associated with that request context
- **THEN** operators can inspect the request and the downstream workflow behavior as related trace activity

### Requirement: V2 provides a local evaluation harness for routed workflows
The system MUST provide a local evaluation harness for key routed workflow scenarios without requiring all results to be uploaded to LangSmith.

The initial eval harness MUST support at least:

- running a small set of workflow examples locally
- evaluating workflow or output quality for critical routed scenarios
- covering final report outcomes once report-review outputs exist

#### Scenario: Developer runs workflow evals locally
- **WHEN** a developer runs the local V2 evaluation harness
- **THEN** the system evaluates the configured workflow scenarios and returns local results
- **THEN** the developer can inspect failures without manually replaying every workflow step
