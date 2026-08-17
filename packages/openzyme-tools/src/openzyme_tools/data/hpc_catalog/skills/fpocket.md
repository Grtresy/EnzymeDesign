# fpocket

Author inputs and command files in the executor-owned workspace, commit a clean revision,
and submit it through the revision-job Host boundary. This document does not provide a
runner command compiler or direct scheduler authority.

## Required Inputs
- structure_path

## Optional Inputs
- chain_id
- output_dir

## Outputs
- detected pocket summary
- pocket ranking files

## Failure Signatures
- missing structure file
- fpocket command exits non-zero

## Example Invocation Shape
```json
{
  "structure_path": "structure_001.pdb"
}
```
