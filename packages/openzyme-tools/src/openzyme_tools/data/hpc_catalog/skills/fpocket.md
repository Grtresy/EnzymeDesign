# fpocket

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
  "structure_path": "artifact_001.pdb"
}
```
