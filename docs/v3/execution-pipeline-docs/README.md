# Execution Pipeline SDK Docs

This directory is the searchable documentation set for executor-authored V3 execution pipelines.

Executor prompts should not embed the full SDK reference. They should tell the executor to search these docs when writing pipeline code.

Useful search keywords:

- `pipeline`
- `artifact read register`
- `bio ncbi uniprot hmmer`
- `bio_tools mafft cdhit hmmbuild hmmalign hmmsearch`
- `preprocess prepare_receptor prepare_ligand`
- `hpc.vina`
- `hpc.fpocket`
- `batch ligand docking`
- `sandbox rules`
- `dry-run`

Recommended reading paths:

- New pipeline authoring: `sdk-overview.md`, then `sandbox-rules.md`
- Registering files: `artifacts.md`
- Bio database fetch/search: `bio.md`
- Sequence-mining toolchain: `bio-tools.md`
- Vina docking: `hpc-vina.md`, then `preprocess.md`
- Pocket detection: `hpc-fpocket.md`
- Many ligands or repeated jobs: `batch-patterns.md`

Examples:

- `examples/vina_single_ligand.py`
- `examples/vina_batch_ligands.py`
- `examples/fpocket.py`
