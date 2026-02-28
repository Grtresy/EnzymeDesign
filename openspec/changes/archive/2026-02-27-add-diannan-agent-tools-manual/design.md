## Context

The change delivers an operator-facing manual for Diannan that makes tool invocation deterministic across mixed deployment modes: system binaries, Spack-managed software, `/opt/tools` wrappers, and standalone SIF containers in `~/containers`.

Current state:
- Tool availability is fragmented across multiple locations and runtimes.
- Invocation style differs by tool family (native CLI vs wrapper script vs container entrypoint).
- Users can identify tools that exist, but not always the correct call contract (input files, output directories, expected artifacts, error signals).

Constraints:
- The workflow must cover the enzyme design stages from evidence to evaluation and update.
- Local development uses `uv` for Python environments; server execution is command-line and scheduler oriented.
- Existing installed tools on Diannan must be treated as first-class and not replaced by redundant installs.

Stakeholders:
- Agent developers who need predictable command contracts.
- Workflow maintainers integrating tools into Snakemake/automation.
- New users onboarding onto Diannan without prior cluster/toolchain context.

## Goals / Non-Goals

**Goals:**
- Define a single authoritative usage manual for Diannan agent-required tools.
- Standardize per-tool command interfaces with explicit input and output format requirements.
- Document invocation patterns for `/opt/tools` wrappers, Spack/native commands, and SIF containers.
- Provide stage-to-tool selection guidance with acceptable replacements.
- Include operational verification criteria so users can confirm successful execution.

**Non-Goals:**
- Rebuild or reinstall the full toolchain.
- Redesign scoring algorithms or workflow business logic.
- Introduce new orchestration behavior beyond documenting invocation contracts.
- Guarantee benchmark-level performance metrics for every tool.

## Decisions

1) Single manual with stable sections and machine-readable conventions
- Decision: Keep one primary manual as the source of truth, with a repeatable section schema per tool.
- Rationale: Minimizes drift and makes it easy for both humans and agents to parse.
- Alternatives considered:
  - Split by workflow stage into many small files: clearer topical grouping, but higher update overhead and version drift risk.
  - Keep ad-hoc README notes: fast initially, but poor consistency and hard automation.

2) Per-tool command contract format is mandatory
- Decision: Each tool entry must include: purpose, entrypoint, prerequisites, required inputs, optional inputs, command pattern, output artifacts, exit/success criteria, and common failure signatures.
- Rationale: The user requirement is that readers can invoke tools directly from docs; this needs explicit I/O contracts.
- Alternatives considered:
  - Narrative-only usage notes: readable but ambiguous for automation.
  - Copying `--help` output verbatim: complete but noisy and not workflow-oriented.

3) Invocation precedence reflects deployed reality on Diannan
- Decision: Prefer `/opt/tools` wrappers when available, then dedicated SIF images, then Spack/native fallback.
- Rationale: Wrappers already encode environment assumptions; SIF provides reproducibility where wrappers are missing.
- Alternatives considered:
  - Spack-first strategy: consistent package manager path, but ignores already curated wrapper workflows.
  - Container-only strategy: reproducible, but unnecessary overhead for existing native installs.

4) Explicit split between local and server responsibilities
- Decision: Document local `uv` environment needs separately from server execution dependencies.
- Rationale: Prevents overloading local machines with heavy inference tooling while keeping developer ergonomics clear.
- Alternatives considered:
  - Unified dependency list without environment split: simpler layout, but leads to incorrect installation expectations.

5) Workflow-stage mapping and substitution matrix are required
- Decision: Add a matrix mapping stages (Evidence, Prompt, Generator, Evaluator, Update/HITL) to primary tools and substitutes.
- Rationale: The workflow accepts functional replacements, so users need deterministic selection rules.
- Alternatives considered:
  - Flat alphabetical tool list only: easier to maintain, but weak guidance for task-oriented execution.

## Risks / Trade-offs

- [Risk] Wrapper behavior changes outside version control (e.g., `/opt/tools` scripts updated) -> Mitigation: include script location and last-verified timestamp fields in the manual.
- [Risk] Container path binding mistakes produce silent empty outputs -> Mitigation: provide canonical bind/path examples and post-run artifact checks.
- [Risk] Divergence between Spack and wrapper-supported versions -> Mitigation: document preferred invocation tier and fallback expectations explicitly.
- [Risk] Tool availability differs between login and compute nodes -> Mitigation: include scheduler-node execution notes and validation commands.
- [Trade-off] One canonical schema increases authoring effort per tool -> Mitigation: improves long-term consistency and agent usability.

## Migration Plan

1. Draft the canonical manual structure and section schema.
2. Populate entries for currently available Diannan tools and SIF images.
3. Validate each command contract against real execution paths and expected outputs.
4. Integrate references into workflow onboarding docs.
5. Update review process so new tools require a command-contract entry before adoption.

Rollback strategy:
- If issues are found, keep the previous ad-hoc references as backup and mark manual sections as provisional until revalidated.

## Open Questions

- Should the command-contract schema be mirrored as JSON/YAML for automatic linting in CI? Yes
- Do we enforce a strict version pin per tool entry, or maintain a tested-version range? 目前工具只有唯一版本并且没有升级的计划，因此 enforce a strict version pin per tool entry
- For SIF tools, should a shared bind-mount policy be mandated across all workflows? 强制统一 bind 规范
