## ADDED Requirements

### Requirement: Non-live readiness hands off without evidence promotion
The `ready_non_live` catalog and report MUST be immutable inputs to real identity discovery and dry-plan construction. A real qualification unit MUST be rebuilt from the resolved subject and current source, build and configuration closure; neither the readiness unit digest nor a recording-backend result MUST be upgraded in place or serialized as real-subject evidence.

#### Scenario: All readiness fixtures pass before identity resolution
- **WHEN** an operator requests a real qualification plan from a complete recording-backend report
- **THEN** the system uses its catalog closure as input but keeps every unresolved real subject blocked

#### Scenario: Readiness digest is copied into a live receipt
- **WHEN** a purported qualified receipt reuses the non-live unit digest without recomputing the real-subject closure
- **THEN** independent verification rejects the receipt
