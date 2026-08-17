# vina

Author inputs and command files in the executor-owned workspace, commit a clean revision,
and submit it through the revision-job Host boundary. This document does not provide a
runner command compiler or direct scheduler authority.

## Required Inputs
- receptor_path
- ligand_path
- center_x
- center_y
- center_z

## Optional Inputs
- size_x
- size_y
- size_z
- exhaustiveness

## Outputs
- docking pose files
- best affinity estimate

## Failure Signatures
- missing receptor or ligand file
- invalid search box configuration
- vina exits non-zero

## Example Invocation Shape
```json
{
  "receptor_path": "candidate_001.pdbqt",
  "ligand_path": "ligand.pdbqt",
  "center_x": 0,
  "center_y": 0,
  "center_z": 0
}
```
