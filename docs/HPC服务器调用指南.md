# HPC Tool Usage Manual

Last updated: 2026-02-26

## 0. Scope and documentation schema

- Canonical manual location: `HPC服务器调用指南.md`
- This file is the single source of truth for tool invocation in the HPC enzyme-design workflow.
- To override in future runs, pass the alternate doc path explicitly in workflow configuration.

Top-level sections in this manual (fixed):
1. `HPC-tool-catalog`
2. `tool-command-contracts`
3. `container-tool-invocation`
4. `workflow-tool-selection-guide`
5. `verification-and-handoff`

### 0.1 Frozen in-scope tool set and canonical entrypoints

#### Native/System + Spack

| Tool | Deployment mode | Canonical entrypoint | Strict pin |
| --- | --- | --- | --- |
| Python runtime | native | `python3` | `Python 3.12.3` |
| Scheduler launcher | native | `srun` | `slurm 25.11.1` |
| Container runtime | native | `apptainer` | `apptainer 1.4.3-dirty` |
| Spack CLI | native | `/opt/spack/bin/spack` | `spack 1.1.0` |
| HMMER (jackhmmer) | Spack | `/opt/spack/opt/spack/linux-icelake/hmmer-3.4-nl4l7rkfm3riinxkpshtf4z2vxdwfw5l/bin/jackhmmer` | `hmmer@3.4` |

#### `/opt/tools` wrapper entrypoints

| Wrapper | Canonical entrypoint |
| --- | --- |
| AlphaFold3 | `/opt/tools/alphafold3` |
| AlphaFold3 short wrapper | `/opt/tools/alphafold3_run` |
| Chai-1 | `/opt/tools/chai-lab` |
| LigandMPNN | `/opt/tools/LigandMPNN` |
| ProteinMPNN | `/opt/tools/ProteinMPNN` |
| SoluableMPNN | `/opt/tools/SoluableMPNN` |
| ColabFold batch | `/opt/tools/colabfold_batch` |
| ColabFold MSA (CPU) | `/opt/tools/colabfold_search` |
| ColabFold MSA (GPU) | `/opt/tools/colabfold_search_gpu` |
| ColabFold local two-step wrapper | `/opt/tools/colabfold_local` |
| Modeller python shim | `/opt/tools/modeller` |
| Rosetta binary directory symlink | `/opt/tools/rosetta` -> `/opt/tools_env/rosetta/source/bin` |

#### `/opt/tools_env` frozen environments

`alphafold3`, `chai-1`, `colabfold`, `DiffDock`, `gaussian`, `LigandMPNN`, `mmseqs2`, `modeller`, `RFdiffusion2`, `rosetta`

#### `~/containers` SIF images

| Image | Canonical image path | Canonical entrypoint |
| --- | --- | --- |
| CaverDock | `~/containers/caverdock-1.2.sif` | `cd-screening` (via `apptainer exec`) |
| fpocket | `~/containers/fpocket.sif` | `fpocket` |
| HH-suite | `~/containers/hhsuite.sif` | `hhblits` |
| P2Rank | `~/containers/p2rank_2.5.1.sif` | `prank` (via `apptainer run`) |
| AutoDock Vina | `~/containers/vina.sif` | `vina` |

### 0.2 Standard command contract fields (mandatory for every tool entry)

Every command contract in this manual must include:

1. Purpose
2. Prerequisites
3. Required inputs (machine-actionable file format and path rules)
4. Optional inputs/flags
5. Command pattern
6. Output artifacts (path + format)
7. Success checks
8. Failure signatures and minimum diagnostics

## 1. HPC-tool-catalog

### 1.1 Stage-based inventory table

| Stage | Tool | Deployment mode | Canonical entrypoint | Runtime context | Node expectation | Last verified |
| --- | --- | --- | --- | --- | --- | --- |
| Evidence | HHblits | SIF | `apptainer exec ~/containers/hhsuite.sif hhblits` | CPU + local/cluster DB mount | login for dry-run, compute for full DB search | 2026-02-26 smoke-ok |
| Evidence | Jackhmmer | Spack | `/opt/spack/.../jackhmmer` | CPU, large sequence DB | compute preferred for large target DB | 2026-02-26 smoke-ok |
| Evidence | ColabFold MSA GPU | wrapper | `/opt/tools/colabfold_search_gpu` | GPU for fast MSA | compute node with GPU | 2026-02-26 entrypoint-ok |
| Prompt | Python prompt assembly | native | `python3` | local `uv` or server python | local preferred | 2026-02-26 smoke-ok |
| Prompt | Config templating | native | `python3` + YAML/JSON files | CPU lightweight | local preferred | 2026-02-26 policy-ok |
| Generator | LigandMPNN | wrapper | `/opt/tools/LigandMPNN` | GPU + model weights in tools env | compute node with GPU | 2026-02-26 smoke-ok |
| Generator | ProteinMPNN/SoluableMPNN | wrapper | `/opt/tools/ProteinMPNN`, `/opt/tools/SoluableMPNN` | GPU + model weights | compute node with GPU | 2026-02-26 entrypoint-ok |
| Generator | Chai-1 fold | wrapper | `/opt/tools/chai-lab fold` | GPU + optional MSA/template APIs | compute node with GPU | 2026-02-26 smoke-ok |
| Evaluator | AlphaFold3 | wrapper | `/opt/tools/alphafold3` or `/opt/tools/alphafold3_run` | GPU + JSON spec | compute node with GPU (A800 preferred) | 2026-02-26 entrypoint-ok |
| Evaluator | fpocket | SIF | `apptainer exec ~/containers/fpocket.sif fpocket` | CPU pocket detection | login for tiny test, compute for batch | 2026-02-26 smoke-ok |
| Evaluator | P2Rank | SIF | `apptainer run ~/containers/p2rank_2.5.1.sif predict` | CPU + Java in image | login for tiny test, compute for batch | 2026-02-26 smoke-ok |
| Evaluator | Vina | SIF | `apptainer exec ~/containers/vina.sif vina` | CPU docking | compute preferred for high throughput | 2026-02-26 smoke-ok |
| Evaluator | CaverDock screening | SIF | `apptainer exec ~/containers/caverdock-1.2.sif cd-screening` | CPU + docking config | compute preferred | 2026-02-26 smoke-ok |
| Evaluator | Rosetta | wrapper | `/opt/tools/rosetta/<app>.linuxgccrelease` | CPU-heavy refinement/scoring | compute node | 2026-02-26 smoke-ok |
| Update/HITL | Modeller scripts | wrapper | `/opt/tools/modeller` | CPU script execution in modeller env | login for small scripts, compute for batch | 2026-02-26 entrypoint-ok |
| Update/HITL | Review/triage scripts | native | `python3` in local `uv` env | local lightweight orchestration | local preferred | 2026-02-26 policy-ok |

### 1.2 Stage substitutes (approved)

| Stage | Primary | Approved substitutes |
| --- | --- | --- |
| Evidence | `hhblits` (SIF) | `jackhmmer` (Spack), `colabfold_search_gpu` |
| Prompt | local `python3` (`uv`) | server `python3` |
| Generator | `LigandMPNN` + `chai-lab fold` | `ProteinMPNN`, `SoluableMPNN`, `alphafold3` |
| Evaluator | `fpocket` + `vina` | `p2rank`, `caverdock`, `rosetta` |
| Update/HITL | `modeller` + local review scripts | `rosetta` refinement, local dashboard tools |

## 2. tool-command-contracts

### 2.1 Native/Spack command contracts

#### Contract: `jackhmmer` (Spack hmmer@3.4)

- Purpose: iterative sequence search for evidence extraction.
- Prerequisites: readable query FASTA and sequence database FASTA; sufficient CPU.
- Required inputs:
  - `query.fasta`: protein FASTA file, one or more records.
  - `target_db.fasta`: searchable protein sequence database.
- Optional inputs:
  - `-N <int>` iterations, `--tblout <file>`, `--domtblout <file>`, `-E <float>`.
- Command pattern:
  - `/opt/spack/opt/spack/linux-icelake/hmmer-3.4-nl4l7rkfm3riinxkpshtf4z2vxdwfw5l/bin/jackhmmer -N 3 --tblout out/hits.tbl query.fasta target_db.fasta`
- Output artifacts:
  - `out/hits.tbl` (tabular per-sequence hits)
  - optional domain table and checkpoint files if requested.
- Success checks:
  - exit code `0`
  - output table exists and has non-header records.
- Failure diagnostics:
  - `Error: Failed to open` -> check file path and read permission.
  - empty hit table with exit `0` -> relax thresholds (`-E`) or verify DB content.

#### Contract: `python3` orchestration scripts

- Purpose: prompt assembly, update logic, and lightweight HITL preprocessing.
- Prerequisites: local `uv` environment or system Python dependencies installed.
- Required inputs:
  - script path (`*.py`)
  - JSON/YAML config path.
- Optional inputs: CLI args such as `--input`, `--output`, `--seed`.
- Command pattern:
  - `python3 scripts/<task>.py --input in/config.json --output out/result.json`
- Output artifacts:
  - JSON/CSV/Markdown according to script contract.
- Success checks:
  - exit code `0`, output file exists and is parseable JSON/CSV.
- Failure diagnostics:
  - `ModuleNotFoundError` -> activate correct environment.
  - `FileNotFoundError` -> verify relative vs absolute input path.

### 2.2 `/opt/tools` wrapper command contracts

#### Contract: `alphafold3` / `alphafold3_run`

- Purpose: structure prediction for evaluation stage.
- Prerequisites: GPU resource and valid AF3 JSON input.
- Required inputs:
  - `input.json` with AF3 schema.
  - writable output directory.
- Optional inputs: scheduler flags (for example `-p A800`).
- Command pattern:
  - `srun -G 1 -p A800 /opt/tools/alphafold3 --json_path input.json --output_dir output_dir`
  - `srun -G 1 -p A800 /opt/tools/alphafold3_run input.json output_dir`
- Output artifacts:
  - prediction artifacts under `output_dir` (model files, logs).
- Success checks:
  - output directory exists and contains non-empty prediction artifacts.
- Failure diagnostics:
  - scheduler reject -> check partition/GPU quota.
  - schema parse errors -> validate `input.json` fields.

#### Contract: `chai-lab fold`

- Purpose: fold complexes from FASTA.
- Prerequisites: GPU; optional remote MSA/template service access.
- Required inputs:
  - `input.fasta`
  - `output_dir`.
- Optional inputs:
  - `--use-msa-server`, `--use-templates-server`.
- Command pattern:
  - `srun -G 1 /opt/tools/chai-lab fold input.fasta output_dir`
- Output artifacts:
  - folded structures and run logs in `output_dir`.
- Success checks:
  - run exits `0`, output contains expected structure files.
- Failure diagnostics:
  - API/network errors -> retry without remote services or switch source.
  - GPU OOM -> lower batch size/workload.

#### Contract: `LigandMPNN` / `ProteinMPNN` / `SoluableMPNN`

- Purpose: sequence redesign from protein structure inputs.
- Prerequisites: GPU and valid PDB input.
- Required inputs:
  - `--pdb_path <input.pdb>`
  - `--out_folder <output_dir>`.
- Optional inputs:
  - `--model_type`, `--temperature`, `--number_of_batches`, residue constraints.
- Command pattern:
  - `srun -G 1 /opt/tools/LigandMPNN --pdb_path input.pdb --out_folder out_dir`
  - same pattern for `ProteinMPNN` and `SoluableMPNN`.
- Output artifacts:
  - designed sequences and optional stats in `out_dir`.
- Success checks:
  - output directory contains generated sequence files.
- Failure diagnostics:
  - missing checkpoint/model path -> verify `/opt/tools_env/LigandMPNN` is intact.
  - malformed PDB -> run structure validation before redesign.

#### Contract: ColabFold wrappers

- Purpose: MSA generation and AF2-style structure prediction.
- Prerequisites: GPU for `search_gpu`; FASTA input.
- Required inputs:
  - `input.fasta`
  - output directories (`msa_dir`, `output_dir`).
- Optional inputs: custom MSA directory in `colabfold_local`.
- Command pattern:
  - `srun -G 1 /opt/tools/colabfold_search_gpu input.fasta msa_dir`
  - `srun -G 1 /opt/tools/colabfold_batch msa_dir output_dir`
  - `srun -G 1 /opt/tools/colabfold_local input.fasta output_dir [msa_dir]`
- Output artifacts:
  - MSA files in `msa_dir`; predictions in `output_dir`.
- Success checks:
  - MSA output not empty and final prediction artifacts exist.
- Failure diagnostics:
  - wrapper two-step errors -> execute explicit `search_gpu` then `batch`.

#### Contract: `modeller`

- Purpose: run modeller scripts in preconfigured environment.
- Prerequisites: modeller script and input templates.
- Required inputs:
  - script file (for example `my_modeller_script.py`).
- Optional inputs: script-level CLI args.
- Command pattern:
  - `/opt/tools/modeller my_modeller_script.py`
- Output artifacts:
  - script-defined PDB/model files.
- Success checks:
  - modeller exits `0` and expected model files are created.
- Failure diagnostics:
  - Python traceback -> inspect script and input template paths.

#### Contract: `rosetta` binaries

- Purpose: scoring/refinement fallback in evaluator/update stages.
- Prerequisites: selected Rosetta app, valid input file format.
- Required inputs:
  - app executable under `/opt/tools/rosetta/`.
  - app-specific flags and input files.
- Optional inputs: score and protocol tuning options.
- Command pattern:
  - `/opt/tools/rosetta/AbinitioRelax.default.linuxgccrelease -help`
  - `/opt/tools/rosetta/<rosetta_app>.linuxgccrelease [flags]`
- Output artifacts:
  - app-specific files (for example score tables, silent files, PDB outputs).
- Success checks:
  - non-empty result files and no fatal line in stderr.
- Failure diagnostics:
  - option parse errors -> run app with `-help` and correct flags.

### 2.3 Common failure signatures and minimum diagnostics

| Tool family | Common failure signatures | Minimum diagnostics |
| --- | --- | --- |
| Native/Spack | `FileNotFoundError`, unreadable DB, empty result sets | verify absolute paths; rerun with relaxed thresholds; record command + exit code |
| `/opt/tools` wrappers | scheduler rejection, `CUDA out of memory`, model/checkpoint missing | verify `srun` partition/GPU request; inspect wrapper path and env; retry with reduced workload |
| SIF tools | bind path not visible in container, missing output directory, non-zero exit from container entrypoint | validate bind map and writable output path; run help command first; inspect container stderr for parser errors |

## 3. container-tool-invocation

### 3.1 Shared Apptainer bind-mount policy (mandatory)

Use one canonical bind policy for all SIF workflows:

```bash
apptainer exec --cleanenv \
  --bind "${WORKDIR}:/work" \
  --bind "${OUTDIR}:/out" \
  --bind "${DBDIR}:/db" \
  --bind "${MODELDIR}:/models" \
  --bind "${TMPDIR}:/tmp" \
  <IMAGE.sif> <ENTRYPOINT> <ARGS...>
```

Policy rules:
- Inputs must be referenced as `/work/...` or `/db/...`.
- Outputs must be written only under `/out/...`.
- Temporary files must use `/tmp`.
- Do not rely on implicit current directory mounts for production runs.

### 3.2 SIF invocation contracts (argument-to-output mapping)

#### Contract: `caverdock-1.2.sif`

- Entrypoint: `cd-screening`
- Required inputs:
  - `/work/screening.yaml` (CaverDock screening config)
- Optional inputs:
  - `-o /out/<dir>`, `-p <threads>`, `--log /out/<file>`
- Command pattern:
  - `apptainer exec ... ~/containers/caverdock-1.2.sif cd-screening /work/screening.yaml -o /out/caverdock`
- Output mapping:
  - `-o /out/caverdock` -> all run artifacts in `/out/caverdock/`.

#### Contract: `fpocket.sif`

- Entrypoint: `fpocket`
- Required inputs:
  - `/work/target.pdb`
  - Host-side validation requires a `.pdb` artifact or metadata `format=pdb`, at least 50 `ATOM`/`HETATM` records, and at least 10 residues.
  - Tiny toy PDB snippets fail as `invalid_fpocket_input` before approval and are not submitted to HPC.
- Optional inputs:
  - `-m`, `-M`, `-D`, chain filters, interaction grid flags.
- Command pattern:
  - `apptainer exec --pwd /out ... ~/containers/fpocket.sif fpocket -f /work/target.pdb`
- Output mapping:
  - produces `/out/target_out/` directory with pocket descriptors and pocket files.

SSH/runner timeout defaults for Host-supervised calls:

- SSH options: `ConnectTimeout=15`, `ServerAliveInterval=30`, `ServerAliveCountMax=2`
- staging timeout: 120 seconds
- preflight timeout: 60 seconds
- remote execution timeout: 7200 seconds
- artifact fetch timeout: 120 seconds

#### Contract: `hhsuite.sif`

- Entrypoint: `hhblits`
- Required inputs:
  - `/work/query.fasta`
  - `/db/<hhblits_database_prefix>`
- Optional inputs:
  - `-n`, `-e`, `-cpu`, `-oa3m`, `-o`
- Command pattern:
  - `apptainer exec ... ~/containers/hhsuite.sif hhblits -i /work/query.fasta -d /db/uniclust30 -oa3m /out/query.a3m -o /out/query.hhr`
- Output mapping:
  - `-oa3m /out/query.a3m` -> aligned MSA.
  - `-o /out/query.hhr` -> ranked match report.

#### Contract: `p2rank_2.5.1.sif`

- Entrypoint: `prank` (via `apptainer run`)
- Required inputs:
  - command (`predict`, `rescore`, etc.)
  - protein input (`-f /work/target.pdb`)
- Optional inputs:
  - `-o /out/p2rank`, `-threads <n>`, `-visualizations <0/1>`
- Command pattern:
  - `apptainer run ... ~/containers/p2rank_2.5.1.sif predict -f /work/target.pdb -o /out/p2rank`
- Output mapping:
  - prediction report files and visualization artifacts under `/out/p2rank/`.

#### Contract: `vina.sif`

- Entrypoint: `vina`
- Required inputs:
  - `/work/receptor.pdbqt`
  - `/work/ligand.pdbqt`
  - center coordinates and box sizes.
- Optional inputs:
  - `--cpu`, `--seed`, `--exhaustiveness`, `--num_modes`, `--energy_range`.
- Command pattern:
  - `apptainer exec ... ~/containers/vina.sif vina --receptor /work/receptor.pdbqt --ligand /work/ligand.pdbqt --center_x 0 --center_y 0 --center_z 0 --size_x 20 --size_y 20 --size_z 20 --out /out/vina_out.pdbqt --log /out/vina.log`
- Output mapping:
  - `--out /out/vina_out.pdbqt` -> docked poses.
  - `--log /out/vina.log` -> run summary and scores.

### 3.3 Post-run validation checks for SIF tools

| Tool | Required output files | Minimum success signal |
| --- | --- | --- |
| CaverDock | `/out/caverdock/` exists and is non-empty | command exits `0`; log contains completion message and no traceback |
| fpocket | `/out/<target>_out/` exists | command exits `0`; pocket descriptor files present |
| HHblits | `/out/query.a3m` and `/out/query.hhr` | command exits `0`; output files non-empty |
| P2Rank | `/out/p2rank/` exists with prediction table | command exits `0`; prediction CSV file exists |
| Vina | `/out/vina_out.pdbqt` and `/out/vina.log` | command exits `0`; log contains scored modes |

## 4. workflow-tool-selection-guide

### 4.1 Stage-to-tool selection matrix

| Workflow stage | Primary tool path | Approved substitute path |
| --- | --- | --- |
| Evidence | `hhblits` in `hhsuite.sif` | Spack `jackhmmer`, wrapper `colabfold_search_gpu` |
| Prompt | local `python3` (`uv`) scripts | server `python3` scripts |
| Generator | `/opt/tools/LigandMPNN` + `/opt/tools/chai-lab fold` | `/opt/tools/ProteinMPNN`, `/opt/tools/SoluableMPNN`, `/opt/tools/alphafold3` |
| Evaluator | `fpocket.sif` + `vina.sif` | `p2rank_2.5.1.sif`, `caverdock-1.2.sif`, `/opt/tools/rosetta/*` |
| Update/HITL | `/opt/tools/modeller` + local review scripts | Rosetta refinement or manual review dashboard |

### 4.2 Deterministic invocation precedence rules

Always choose invocation mode in this order:

1. `/opt/tools` wrapper (if available and smoke-check passes)
2. SIF container invocation under shared bind policy
3. Spack/native fallback

Decision tie-breakers:
- If a wrapper exists but is missing dependencies, switch to SIF and log the fallback reason.
- If both wrapper and SIF paths are unavailable, use Spack/native and pin exact executable path.
- Record the chosen mode per stage in run metadata.

### 4.3 Local vs server execution boundaries

Local (`uv`) scope:
- prompt assembly, metadata transforms, report rendering, lightweight HITL preprocessing.

Server (HPC) scope:
- GPU inference (`alphafold3`, `chai-lab`, MPNN wrappers).
- large MSA/database search (`hhblits`, `jackhmmer`, ColabFold search).
- docking/pocket scoring (`vina`, `fpocket`, `p2rank`, `caverdock`).

Boundary rule:
- Compute-intensive stages must run on server resources; local environments are for orchestration and lightweight development only.

## 5. verification-and-handoff

### 5.1 Smoke checks run on 2026-02-26

| Tier | Command | Result |
| --- | --- | --- |
| Native | `python3 --version` | `Python 3.12.3` |
| Native | `apptainer --version` | `apptainer version 1.4.3-dirty` |
| Spack | `/opt/spack/bin/spack find --format "{name}@{version}" hmmer` | `hmmer@3.4` |
| Wrapper | `/opt/tools/chai-lab --help` | help text returned (entrypoint valid) |
| Wrapper | `/opt/tools/LigandMPNN --help` | help text returned (entrypoint valid) |
| Wrapper | `/opt/tools/rosetta/AbinitioRelax.default.linuxgccrelease -help` | help text returned (entrypoint valid) |
| SIF | `apptainer exec ~/containers/fpocket.sif fpocket -h` | `fpocket 4.0` usage returned |
| SIF | `apptainer exec ~/containers/hhsuite.sif hhblits -h` | `HHblits 3.3.0` usage returned |
| SIF | `apptainer run ~/containers/p2rank_2.5.1.sif help` | `P2Rank 2.5.1` help returned |
| SIF | `apptainer exec ~/containers/vina.sif vina --version` | `AutoDock Vina 1.1.2` |
| SIF | `apptainer exec ~/containers/caverdock-1.2.sif cd-screening -h` | usage returned (entrypoint valid) |

### 5.2 Strict pin set

#### Wrapper SHA256 pins

```text
82c55543ea5cfef4ee63031635de070f2594b0281a25c6df2664e254cb588ef8  /opt/tools/alphafold3
be75387f273a36d88c770e3530fd673b3164bbfda5f02ac1aa2ea4de3277d540  /opt/tools/alphafold3_run
22dad4a1e15bb807b0d7e3f7bdbcf4a45ce8d9d5290201bce1898731d752df42  /opt/tools/chai-lab
66ec60614b975bc54bd9d44b4842a0be4b01514a57672b5d38dd15c4c77f993c  /opt/tools/LigandMPNN
8305105a18b166c5d66a76e1ab5824230e15e7bd8108a5e5e2aa4f4b7162c99b  /opt/tools/ProteinMPNN
935f9447640c728ad5e711c7f8e835a10f89f2f2d9c520ce4bf8920ed68797eb  /opt/tools/SoluableMPNN
7cceaf5a001012d804c73329dd5e7906f15ecb4570d8487a40c8cc78df2496ef  /opt/tools/colabfold_batch
d74a98a17f378eaee1b890e9eb3ca66f18cebc72f9a22baedbc0318429e2a75b  /opt/tools/colabfold_search
c560f3e9046b7844e837928a221eb6e7544d2d95051567de7676ed8f74a6145e  /opt/tools/colabfold_search_gpu
9d64d8a00a8e5ddc46ec3a3632da705e290c2b711398e840b99d61aa6552090c  /opt/tools/colabfold_local
763bed20bf8446de509a7b5c6d9a38772c10fe99c47f3b47d94b77ce59b897f8  /opt/tools/modeller
```

#### Container SHA256 pins

```text
279db29700fa63747d8fd9bfacd17740ca380afc597a2761ea11ef73e8023223  /home/grtresy/containers/caverdock-1.2.sif
11a9474117b6710278323e89840c330853ee6666287b46661374cf5d9633c348  /home/grtresy/containers/fpocket.sif
05aad001a59a9230282011379866e709e0deb3b5df25bde6f8ca6c6ded92b59e  /home/grtresy/containers/hhsuite.sif
33fea1cd0939f1f0120454a26dd92aadb7f7972a842534ac43fd7c37087891d5  /home/grtresy/containers/p2rank_2.5.1.sif
49623963e698b32b0bc8cbc3a8ae4d7902f13e4bebdf8af69239b04d981d1d24  /home/grtresy/containers/vina.sif
```

### 5.3 Spec coverage review checklist

| Requirement area | Covered in this manual |
| --- | --- |
| Stage inventory + substitutes | Sections `1.1`, `1.2`, `4.1` |
| Deployment mode + entrypoint metadata | Sections `0.1`, `1.1` |
| Runtime context, node expectation, verification state | Section `1.1` |
| Standardized command contract schema | Sections `0.2`, `2.1`, `2.2` |
| Input/output format requirements | Sections `2.1`, `2.2`, `3.2` |
| Failure signatures + diagnostics | Sections `2.3`, `3.3` |
| Canonical SIF bind policy | Section `3.1` |
| SIF argument-to-output mapping | Section `3.2` |
| Post-run SIF validation checks | Section `3.3` |
| Invocation precedence and local/server boundary | Sections `4.2`, `4.3` |

### 5.4 Onboarding and maintenance notes

When adding a new tool, all of the following are mandatory before adoption:

1. Add catalog row in Section `1.1` with stage, mode, entrypoint, runtime context, node expectation, and last-verified date.
2. Add full command contract in Section `2` (all eight required fields).
3. If container-based, add contract and validation row in Section `3`.
4. Update stage selection matrix and precedence impact in Section `4`.
5. Run at least one smoke check command and add strict pin entry in Section `5.1` and `5.2`.

No workflow tool may be merged into production usage unless this manual has a corresponding command-contract entry.
