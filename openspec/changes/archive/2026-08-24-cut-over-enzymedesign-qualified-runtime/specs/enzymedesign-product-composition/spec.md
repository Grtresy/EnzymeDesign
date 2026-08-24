## ADDED Requirements

### Requirement: Qualified runtime cutover advertises only the adopted profile closure
The current EnzymeDesign cutover MUST adopt and advertise only the exact Batch 1 profiles `base`, `research-provider`, `hpc-primary`, `hmmer` and `docking`. AlphaFold MUST remain a visible deferred optional profile with `qualified=false`, `adopted=false`, `cutover=false` and no effective affordance. Batch 1 adoption MUST NOT erase or promote the Batch 2 verdict.

#### Scenario: Product catalog still declares AlphaFold after Batch 1 cutover
- **WHEN** the structural Distribution contains the AlphaFold Plugin and Driver but the deployment has no AlphaFold adopted facts
- **THEN** inspection reports it as mounted/deferred while affordance resolution exposes no qualified AlphaFold route

