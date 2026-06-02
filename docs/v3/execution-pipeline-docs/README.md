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
- `stage_artifact`
- `fetch_outputs`
- `batch ligand docking`
- `sandbox rules`
- `dry-run`

Recommended reading paths:

- New executor authoring: `sandbox-rules.md`, then `sdk-overview.md`
- AOX/HMM live cutover: `aox-hmm-live.md`
- Moving files between catalog and sandbox: `artifacts.md`
- Bio database fetch/search: `bio.md`
- Sequence-mining toolchain: `bio-tools.md`
- Vina docking: `hpc-vina.md`, then `preprocess.md` (`hpc.workspace + docking.vina`)
- Pocket detection: `hpc-fpocket.md` (`hpc.workspace + structure_tools.fpocket`)
- Many ligands or repeated jobs: `batch-patterns.md`

Stable boundary:

- The stable executor-facing `hpc` namespace is placement / remote workspace / declarative stage-fetch.
- Domain tool operations use `bio_tools`, `structure_tools`, and `docking`. Public executor docs and examples must not expose runner-backed tool shorthands under `hpc`.
- Regardless of namespace, executor code must use Host-supervised SDK calls and must not call SSH, Slurm, runner config, external network clients, or Host artifact paths directly.

Examples:

- `examples/vina_single_ligand.py`
- `examples/vina_batch_ligands.py`
- `examples/fpocket.py`
