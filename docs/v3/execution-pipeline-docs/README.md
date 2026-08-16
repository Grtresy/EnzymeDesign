# Execution Pipeline SDK Docs

> Pipeline 从 artifact catalog/staging 迁移到 native file、immutable revision 和
> executor workspace 的候选合同见
> [../file-workspace-migration.md](../file-workspace-migration.md)。正式 cutover 前不得把
> candidate SDK 当作 current runner contract 或隐藏 fallback。

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

- C8 stable login data plane 是 owner-scoped `ExecutorHpcWorkspace`。executor 可用 `hpc.workspace.request/inspect/verify/sync_source` 取得 exact workspace 与 revision identity，再通过 `workspace.exec` 的短期 scoped credential 原生使用 SSH、Git/LFS、rsync/scp和root内CRUD；不得读取runner sidecar、其他owner/generation root或Host path。
- `hpc.workspace.sync_source` 只返回 exact private checkpoint或immutable publication ref/commit/tree/LFS closure；fetch、checkout、merge、rebase、cherry-pick和冲突处理仍由agent显式决定。它不force-update/delete checkpoint，不创建publication、handoff、task terminal或job result。
- Login/file credential没有`scheduler.submit`/`sbatch` authority。C9前所有runner payload、reservation、resume与job submit均以`workspace_revision_execution_required`硬关闭；不得回退到artifact staging、Host output fetch、shared account或legacy RunSpec。
- Compute payload 仍不得携带`.git`、Git/LFS binary、repository credential、LFS endpoint或object-store locator；具体revision-to-compute实现属于C9。
- The Host/runner lifecycle credential is a server-issued opaque `run_id`; raw Slurm job IDs, remote directories, and inline recovery RunSpecs never cross the public runner boundary.
- A durable SDK call may suspend its exact sandbox process while approval or an external effect is pending. Executor code still observes one request/response call; it must not invent a polling/replay loop, replacement operation, or a new idempotency key to recover transport ambiguity.
- `ControlledOperationExecution` is the sole external-effect owner. Only a proven pre-effect failure may receive a bounded same-phase recovery; `dispatch_in_doubt` is a fail-closed reconciliation state, not permission to retry.
- A failed run does not grant permission to hide or replay it. New scientific
  attempt `@3` keeps the full occurrence universe and allows only explicit
  same-attempt disposition/adoption/materialization; cross-attempt reuse is
  forbidden.
- The scientific attempt's exact task assignee owns `scientific.attempt.close`.
  For formal AOX, the request must carry the persisted source-bound
  `aox_final_deliverable_validation_receipt@1`; execution completion and report
  handoff must cite and revalidate the same receipt. Immutable closure, task
  completion, report publication, and resident-master response delivery remain
  independent facts, and no companion response binding is created.
- Runner-owned per-target ControlMaster reuse is transport infrastructure. It does not provide a persistent remote shell, preserve cwd/environment, or let executor code control SSH options.

Examples:

- `examples/vina_single_ligand.py`
- `examples/vina_batch_ligands.py`
- `examples/fpocket.py`
