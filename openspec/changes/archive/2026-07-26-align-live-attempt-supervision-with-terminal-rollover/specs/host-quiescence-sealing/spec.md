## ADDED Requirements

### Requirement: Local process settlement is distinct from scope quiescence
The Host MUST distinguish a mutation scope's freeze/quiescence/seal lifecycle from the local process-settlement proof used to hand a root back after an exact process epoch retires. Local settlement MUST require zero active registered writers and a stable bounded authority snapshot, but it MUST NOT require every scope to be terminal. It MUST NOT issue a scope quiescence receipt, seal a scope, or infer workflow completion.

#### Scenario: Writer-free open scope is handed off
- **WHEN** an exact child process epoch has retired, the bounded mutation-authority snapshot is stable, and a nonterminal scope contains no active writers
- **THEN** local settlement may succeed while the scope remains unchanged for later fenced writer admission

#### Scenario: Active writer blocks local settlement
- **WHEN** any writer in the bounded authority snapshot remains `registered` or `retiring`
- **THEN** local settlement fails and cannot be upgraded by process idleness or a terminal task

#### Scenario: Local settlement is observed twice
- **WHEN** child and parent independently project the same canonical authority rows around exact process retirement
- **THEN** both projections yield the same bounded digest without mutating authority state

#### Scenario: Product topology is malformed
- **WHEN** local writers are zero but the current scope has an invalid product identity, parent, kind, or lifecycle relationship
- **THEN** local settlement remains only a process fact and the responsible product/Core projection rejects the topology
