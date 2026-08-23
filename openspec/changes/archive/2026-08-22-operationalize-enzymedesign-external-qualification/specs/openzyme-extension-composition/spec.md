## ADDED Requirements

### Requirement: External operational runtimes derive from qualification-aware bindings
An external Adapter or Driver operational runtime MUST be constructed from the exact selected component binding plus explicit route/subject/configuration identity and credential locator policy. Composition MUST reject a separately supplied runtime, endpoint, target, credential source or backend whose identity is absent from or differs from that binding.

#### Scenario: Selected metadata and runtime endpoint differ
- **WHEN** composition metadata names one Provider configuration but the supplied runtime targets another endpoint
- **THEN** activation fails before credential resolution or external effect

### Requirement: Qualification blockers never trigger operational fallback
When an external route lacks a current exact qualification receipt, composition MAY keep its structurally valid Plugin mounted as degraded, but MUST omit the route from effective qualified affordances and expose a typed blocker. It MUST NOT select another Adapter, Provider, target, credential, operation or anonymous mode unless the Agent explicitly selects a separately qualified advertised route.

#### Scenario: Preferred Slurm target is unqualified
- **WHEN** the selected target has no valid exact receipt and another target is healthy
- **THEN** the first route is blocked and the harness presents only independently qualified alternatives without silently resubmitting
