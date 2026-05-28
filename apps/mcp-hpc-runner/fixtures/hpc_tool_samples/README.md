# HPC Tool Samples

Canonical committed smoke-test inputs for `mcp-hpc-runner` tool contracts.
These files are intentionally small and are only for runner/tool availability,
staging/fetch, and output-validation smoke tests.

## Layout

| Directory | Tools | Files |
| --- | --- | --- |
| `aox_hmm/` | MAFFT, CD-HIT, HMMER CLI | `input_sequences.fasta`, `msa.sto`, `search_targets.fasta`, `run_hpc_sif_smoke.sh` |
| `fpocket/` | fpocket, P2Rank-style pocket smoke | `target.pdb` |
| `vina/` | AutoDock Vina | `receptor.pdbqt`, `ligand.pdbqt` |

Historical run outputs belong under `.mcp_hpc_runner/artifacts/` or
`.mcp_hpc_runner/contract_runs/`; they are not canonical input samples.
