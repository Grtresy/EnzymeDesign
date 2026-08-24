## ADDED Requirements

### Requirement: External runtime cutover sealing includes effect and first-live boundaries
Host quiescence sealing for EnzymeDesign cutover MUST enumerate every selected external writer surface, prove zero unsettled and unknown effects, bind the exact backup set and record whether first-live acceptance has occurred. A seal before first live MUST permit only exact compare-and-restore; a seal at or after accepted/unknown first live MUST require forward-only reconciliation and repair.

#### Scenario: Runner is isolated but one Provider attempt is unknown
- **WHEN** all writers stop while one external attempt still has unknown effect certainty
- **THEN** the quiescence seal is not cutover-ready and activation remains blocked

