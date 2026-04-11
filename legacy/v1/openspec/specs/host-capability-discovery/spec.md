## ADDED Requirements

### Requirement: Host exposes a lightweight capability registry for agent-selectable MCP servers
The system MUST provide a Host-maintained capability registry that exposes lightweight MCP capability summaries to agents instead of injecting all tools, resources, and prompts schemas into the initial decision context.

Each capability summary MUST include at least:

- a stable `capability_id` or equivalent identifier
- the backing server or provider identity
- a concise purpose description
- `use_when` guidance or equivalent applicability hints
- the primary result shape or output form
- latency or cost hints, or equivalent usage guidance
- a handle that can be used to inspect a detailed contract

The registry MUST support at least:

- including only capabilities that agents are expected to discover and choose explicitly
- excluding internal infrastructure-only MCP servers or hidden runtime-only capabilities
- preserving a stable mapping from summary entries to inspectable detail contracts and executable runtime actions

#### Scenario: Agent receives capability summaries instead of all tool schemas
- **WHEN** Host prepares MCP-related context for a new decision round
- **THEN** Host provides capability registry summaries rather than the complete schema for every MCP server
- **THEN** the agent can first decide whether a capability is relevant based on purpose and applicability

### Requirement: Host can inspect and expand one capability into a detailed contract on demand
The system MUST allow an agent or runtime service to request the detailed contract for exactly one capability and MUST return only that capability's normalized detail contract.

Each detail contract MUST include at least:

- the tools exposed by that capability and what each tool is used for
- the availability of relevant resources and prompts
- the core parameters or inputs of the primary tools
- capability-specific selection guidance for choosing among the tools

Inspect results MUST satisfy all of the following:

- they are requested by `capability_id` or an equivalent stable handle
- they only expand the requested capability
- they return a structured Host-normalized contract rather than raw README or schema dumps

#### Scenario: Agent inspects one capability before choosing a concrete tool
- **WHEN** an agent sees a capability summary and determines that capability may be relevant
- **THEN** Host can return a normalized detail contract for only that capability
- **THEN** the agent can choose a concrete tool using that detail contract without requiring full schemas for unrelated capabilities

### Requirement: Capability detail visibility is bounded to a short-lived decision scope
The system MUST bound inspected capability detail contracts to a short-lived decision scope so that one inspect operation does not permanently pollute all later agent context.

The decision scope MUST support at least:

- `episode_id`
- the current `active_state_version` or equivalent freshness anchor
- a `role` or equivalent `agent_id` dimension

The scope semantics MUST ensure that:

- inspected detail is visible only within the current scoped decision window
- later decision windows return to summary-only visibility unless a new inspect occurs
- Host MAY cache detail contracts internally but MUST NOT keep them permanently visible to the agent by default
- detail visibility for one role or agent MUST remain isolated from other roles or agents

#### Scenario: Detailed contract expires after the current decision window
- **WHEN** Host expands a capability detail contract for a given role and `active_state_version`
- **THEN** that detailed contract is only visible within that decision scope
- **THEN** a later decision window defaults back to summary-only visibility unless the capability is inspected again

#### Scenario: A capability inspected by one role is not implicitly visible to another role
- **WHEN** one role or agent inspects a capability during an active decision scope
- **THEN** Host only exposes that detailed contract to the inspecting role or agent for that scope
- **THEN** another role or agent does not automatically inherit the inspected detail

### Requirement: Capability summaries can be auto-generated and selectively overridden
The system MUST support generating baseline capability summaries from MCP metadata while also allowing selected capabilities to use Host-provided overrides.

Summary resolution MUST follow this priority order:

- Host override
- MCP-provided metadata
- Host auto-generated fallback derived from tools, resources, and prompts descriptions

The generated or overridden summary MUST be able to express:

- purpose
- applicability hints
- result shape
- distinguishing notes or boundaries compared with other capabilities

#### Scenario: Core capability uses an overridden summary while another exposed capability uses generated metadata
- **WHEN** Host prepares summaries for multiple agent-selectable capabilities
- **THEN** Host uses an override when one is configured for that capability
- **THEN** Host falls back to MCP metadata or auto-generated summaries for exposed capabilities without overrides

### Requirement: Host records capability discovery and inspection as auditable workflow events
The system MUST record capability discovery and inspection as auditable workflow events so later analysis can explain why the agent saw a capability and how that led to a tool choice.

Each capability-related audit event MUST include at least:

- the `capability_id`
- the event type such as summary-considered, detail-inspected, or tool-selected
- the associated role or agent identifier
- the related episode or decision scope
- a timestamp

#### Scenario: Decision trace shows that a detailed contract was explicitly inspected
- **WHEN** an agent inspects a capability and then chooses one of its tools
- **THEN** the workflow audit trail records the inspect event for that capability
- **THEN** later readers can distinguish that tool choice from one made against an initial full-schema context
