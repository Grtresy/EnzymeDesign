# Execution Pipeline SDK Docs

This directory is the searchable documentation set for executor-authored V3 execution pipelines and persistent executor sandboxes.

Executor prompts should not embed the full SDK reference. They should tell the executor to search these docs when editing files in its sandbox, materializing artifacts, writing pipeline code, snapshotting source, and running sandbox dry-run / execution through the Host supervisor.

Useful search keywords:

- `persistent sandbox`
- `sandbox file command`
- `artifact materialize register snapshot_code`
- `pipeline`
- `artifact read register`
- `bio ncbi uniprot hmmer`
- `bio_tools mafft cdhit hmmbuild hmmalign hmmsearch`
- `aox hmm prompt e2e single_plan approval`
- `aox hmm live fixed deliverables`
- `preprocess prepare_receptor prepare_ligand`
- `tool adapter external bridge`
- `hpc placement`
- `runner_failure@1 staging phase`
- `durable operation effect certainty continuation`
- `stage_artifact`
- `fetch_outputs`
- `batch ligand docking`
- `sandbox rules`
- `dry-run`

Recommended reading paths:

- New executor authoring: `sandbox-rules.md`, then `sdk-overview.md`
- AOX/HMM live cutover: `aox-hmm-live.md`
- AOX motif rule scoring contract and golden boundary: `aox-motif-rule-score-v1.md`
- AOX real-sequence similarity, CD-HIT membership binding, and graph schemas:
  `aox-sequence-similarity-v1.md`
- Moving files between catalog and sandbox: `artifacts.md`
- Bio database fetch/search: `bio.md`
- Sequence-mining toolchain: `bio-tools.md`
- Vina docking: `hpc-vina.md`, then `preprocess.md` (`hpc.workspace + docking.vina`)
- Pocket detection: `hpc-fpocket.md` (`hpc.workspace + structure_tools.fpocket`)
- Many ligands or repeated jobs: `batch-patterns.md`
- Host/runner lifecycle boundary: `runner-opaque-run-id.md`
- Runtime/HPC ownership and recovery boundary: `../07-runtime-hpc-reliability.md`
- Failure recovery, selected-chain attempt authority and closure:
  `../08-failure-recovery-and-scientific-attempts.md`

Stable boundary:

- The stable executor-facing `hpc` namespace is placement / remote workspace / declarative stage-fetch.
- Domain tool operations use `bio_tools`, `structure_tools`, and `docking`. Public executor docs and examples must not expose runner-backed tool shorthands under `hpc`.
- Regardless of namespace, executor code must use Host-supervised SDK calls and must not call SSH, Slurm, runner config, external network clients, or Host artifact paths directly.
- The Host/runner lifecycle credential is a server-issued opaque `run_id`; raw Slurm job IDs, remote directories, and inline recovery RunSpecs never cross the public runner boundary.
- A durable SDK call may suspend its exact sandbox process while approval or an external effect is pending. Executor code still observes one request/response call; it must not invent a polling/replay loop, replacement operation, or a new idempotency key to recover transport ambiguity.
- `ControlledOperationExecution` is the sole external-effect owner. Only a proven pre-effect failure may receive a bounded same-phase recovery; `dispatch_in_doubt` is a fail-closed reconciliation state, not permission to retry.
- A failed run does not grant permission to hide or replay it. New scientific
  attempt `@3` keeps the full occurrence universe and allows only explicit
  same-attempt disposition/adoption/materialization; cross-attempt reuse is
  forbidden.
- Runner-owned per-target ControlMaster reuse is transport infrastructure. It does not provide a persistent remote shell, preserve cwd/environment, or let executor code control SSH options.

Examples:

- `examples/vina_single_ligand.py`
- `examples/vina_batch_ligands.py`
- `examples/fpocket.py`
