## ADDED Requirements

### Requirement: Real qualification batches preserve profile closure
EnzymeDesign MUST define Batch 1 as `base`, `research-provider`, `hpc-primary`, `hmmer` and `docking`, and Batch 2 as `alphafold`. Each batch MUST have an independent identity closure, dry-plan digest, occurrence authorization, budget, receipt set and verdict. An unresolved optional profile MUST remain explicitly blocked rather than disappearing from the claimed batch, and Batch 2 state MUST NOT weaken or broaden Batch 1 evidence.

#### Scenario: AlphaFold resources are unresolved
- **WHEN** Batch 1 closes while AlphaFold image, model or database identity remains missing
- **THEN** Batch 1 may be adjudicated for its exact profiles and Batch 2 remains `blocked_identity`

#### Scenario: One Batch 1 optional profile is incomplete
- **WHEN** docking lacks one required exact operation receipt
- **THEN** docking remains unqualified and no Batch 1 claim states that all five profiles qualified
