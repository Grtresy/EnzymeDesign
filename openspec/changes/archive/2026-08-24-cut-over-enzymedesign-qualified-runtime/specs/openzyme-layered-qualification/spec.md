## ADDED Requirements

### Requirement: Deployment source compatibility is explicit and non-transitive
A cutover using qualification evidence from an earlier source MUST bind both source identities and an independently verified proof that every qualified owner/unit/build/configuration/subject/validator closure is unchanged. This proof MAY permit cutover-only deployment and adoption implementation paths to differ, but MUST NOT relabel the deployment source as qualified, extend receipt validity, or authorize a live occurrence.

#### Scenario: Deployment source contains a cutover executor added after qualification
- **WHEN** the qualified component closure is byte-identical and the only source delta is the inventoried cutover executor and governance artifacts
- **THEN** the cutover receipt retains the original qualification source and the distinct deployment source

