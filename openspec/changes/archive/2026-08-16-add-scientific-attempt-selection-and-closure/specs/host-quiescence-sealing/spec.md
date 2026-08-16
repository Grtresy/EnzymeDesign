## ADDED Requirements

### Requirement: Scientific closure consumes but does not redefine quiescence
A scientific attempt closure SHALL reference an exact valid quiescence receipt for the same attempt mutation scope and generation. The closure service MUST independently verify selection and operation semantics; the quiescence service MUST remain ignorant of adopted scientific roles and MUST NOT infer scientific success, failure, or task status.

#### Scenario: Quiescent scope has incomplete selection
- **WHEN** all writers retire but an operation lacks disposition
- **THEN** the quiescence receipt may remain valid while scientific attempt closure is rejected

#### Scenario: Complete selection has an active writer
- **WHEN** all scientific roles and dispositions verify but the mutation scope is not quiescent
- **THEN** selection may be sealed but attempt closure is withheld
