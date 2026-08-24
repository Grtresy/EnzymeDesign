## ADDED Requirements

### Requirement: Standard owns an executable resident-teammate Host launcher
`openzyme-standard` SHALL provide an executable entry point that constructs the exact Standard Distribution, file-backed SQLite Store, configured Git/LFS workspace Adapter, runtime Adapter, provisioning/runtime workers and generic Host app. Startup and shutdown MUST be bounded, explicit and free of optional vertical Plugin imports.

#### Scenario: Start Standard from explicit configuration
- **WHEN** operator supplies valid Store/workspace/repository/runtime configuration
- **THEN** the launcher preflights the selected bindings, starts the Host and workers, and publishes the exact release identity

#### Scenario: Required configuration is missing
- **WHEN** repository binding, durable root or selected Adapter configuration is absent
- **THEN** startup fails with a structured safe diagnostic and does not choose an in-memory or alternate implementation

#### Scenario: Stop Standard
- **WHEN** the process receives a supported shutdown signal
- **THEN** admission, workers, runtime owner and Store retire in owner order without marking Tasks or Sessions complete

### Requirement: Plugin-free Standard exposes a complete Direct collaboration baseline
Standard SHALL declare and mount Kernel collaboration/inspection/workspace tool runtimes and a closed role exposure policy. A ready master MUST receive the stable Direct collaboration baseline, while unavailable optional capabilities remain absent rather than stubbed.

#### Scenario: Admit a Standard master turn
- **WHEN** a ready Plugin-free Session is drained
- **THEN** the provider sees world/capability inspection, task, delegation, protocol, approval and role-appropriate workspace verbs

#### Scenario: Request an optional vertical tool
- **WHEN** the model or client asks for an undeclared biological/HPC tool
- **THEN** capability inspection reports it absent without loading an optional package or fallback runtime

### Requirement: Standard has a fresh file-backed non-live product E2E
Standard acceptance SHALL construct its real Distribution and public Host surfaces from empty temporary roots, use deterministic fake/no-effect boundaries, and prove create-to-restart resident collaboration closure. No direct database seeding of post-bootstrap workspace/runtime truth is permitted.

#### Scenario: Complete the Standard loop
- **WHEN** the E2E creates a Session, ticks provisioning, posts a message and submits an explicit drain
- **THEN** it observes ready workspace, queued-before-drain semantics, assistant transcript and unchanged Task terminal state unless `task.finish` was called

#### Scenario: Restart the Standard loop
- **WHEN** the first composition retires and another opens the same roots
- **THEN** transcript, authority, readiness and collaboration identities are recovered without repeating provisioning or provider effects

#### Scenario: Attempt a live effect in Standard E2E
- **WHEN** code attempts network/provider/SSH/HPC/browser access
- **THEN** the deny guard fails the qualification and records no success receipt
