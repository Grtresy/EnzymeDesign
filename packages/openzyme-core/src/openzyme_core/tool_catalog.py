from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from openzyme_runtime import AgentStepContext
from openzyme_runtime import ToolSpec
from openzyme_runtime import ToolRuntime

from .engines import EngineRegistry
from .sandbox_runtime import EXEC_MAX_TIMEOUT_SECONDS
from .task_evidence import task_finish_evidence_refs_schema
from .teammate_roster import TEAMMATE_ROLE_NAMES


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    tool_name: str
    description: str
    input_schema: dict[str, Any]

    def to_tool_spec(self) -> ToolSpec:
        return ToolSpec(
            tool_name=self.tool_name,
            description=self.description,
            input_schema=self.input_schema,
        )

    def to_openai_tool(self) -> dict[str, Any]:
        # Compatibility helper only. Product runtime model calls should convert
        # ToolDescriptor -> ToolSpec -> ProviderToolAdapter instead.
        return self.to_tool_spec().to_openai_tool()


def artifact_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_name="artifact.list",
            description=(
                "List safe session artifact records or artifacts scoped to a task/invocation. "
                "The serialized response has a hard 100k-character budget and reports "
                "returned_count/truncated_by_budget; continue from next_offset without skipped "
                "records. Per-artifact metadata and free text are bounded, with omitted-field "
                "digests and exact or root-only artifact.get read scope. Results never include "
                "Host storage_uri or local paths."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "invocation_id": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "code",
                            "log",
                            "sequence",
                            "structure",
                            "report",
                            "research_dossier",
                            "result",
                            "cache",
                            "other",
                        ],
                    },
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 0, "maximum": 50},
                },
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.create_text",
            description=(
                "Create a new immutable Python pipeline source artifact in the current session. "
                "The artifact is stored as kind=code, format=python, semantic_type=pipeline_source, "
                "with SHA-256 content_digest and version metadata. Results never include Host paths."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Safe basename ending in .py, for example pipeline.py.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete UTF-8 Python source text for the artifact.",
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["filename", "content"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.patch_text",
            description=(
                "Create a new immutable version of a Python pipeline source artifact from complete patched "
                "UTF-8 source text. Requires base_artifact_id and matching base_content_digest for concurrency "
                "control; the old artifact is not overwritten."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "base_artifact_id": {"type": "string"},
                    "base_content_digest": {"type": "string"},
                    "content": {
                        "type": "string",
                        "description": "Complete patched UTF-8 Python source text.",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional safe .py basename; defaults to the base artifact filename.",
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["base_artifact_id", "base_content_digest", "content"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.diff_text",
            description=(
                "Return a bounded unified diff between two Python pipeline source artifacts or versions. "
                "Results include safe artifact metadata and content digests, never Host paths."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "base_artifact_id": {"type": "string"},
                    "target_artifact_id": {"type": "string"},
                    "context_lines": {"type": "integer", "minimum": 0, "maximum": 20},
                },
                "required": ["base_artifact_id", "target_artifact_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.get",
            description=(
                "Read one safe artifact catalog record and linked engine metadata by artifact_id. "
                "Large linked output fields are summarized by default; use path/offset/limit from read_hint "
                "to page fields such as output_payload.evidence_items. When path targets a large dict, "
                "the result returns pageable keys; only safe path segments have exact child paths. Large "
                "strings are pageable by character offset. A missing path reports the deepest resolved "
                "prefix, missing segment, parent type, and a bounded parent read hint while retaining "
                "top-level options. Results never include Host paths."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 0, "maximum": 12000},
                    "include_full": {"type": "boolean"},
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.preview",
            description="Preview a UTF-8 text artifact by artifact_id without exposing the Host storage path.",
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "lines": {"type": "integer", "minimum": 1, "maximum": 200},
                    "limit": {"type": "integer", "minimum": 0, "maximum": 50000},
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.read_text",
            description="Read a UTF-8 text artifact by character offset and bounded limit.",
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 0, "maximum": 50000},
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.range",
            description="Read a UTF-8 text artifact by 1-based line range, suitable for logs, PDB, FASTA, JSON, and Markdown.",
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifacts.materialize",
            description=(
                "Copy or map an authorized catalog artifact into the executor sandbox input tree. "
                "The /workspace/input mount is Host-managed and read-only to the sandbox process: "
                "materialize creates the requested target and parent directories, so caller source "
                "must not mkdir, write, or pre-create them. Returns only a sandbox-safe /workspace "
                "path and digest; never returns Host storage paths."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "sandbox_workspace_id": {"type": "string"},
                    "artifact_id": {"type": "string"},
                    "target": {"type": "string"},
                    "mode": {"type": "string", "enum": ["copy", "readonly"]},
                },
                "required": ["sandbox_workspace_id", "artifact_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifacts.snapshot_code",
            description=(
                "Seal source files from /workspace/src as an immutable CODE snapshot for sandbox provenance. "
                "The returned payload contains source_snapshot_artifact_id and source_tree_digest."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "sandbox_workspace_id": {"type": "string"},
                    "paths": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "entrypoint": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["sandbox_workspace_id", "entrypoint"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifacts.register",
            description=(
                "Seal a file or directory under /workspace/output into Host-owned artifact storage and create "
                "an immutable artifact catalog record. Requires an existing source snapshot."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "sandbox_workspace_id": {"type": "string"},
                    "path": {"type": "string"},
                    "kind": {"type": "string"},
                    "format": {"type": "string"},
                    "validation_profile": {
                        "type": "string",
                        "enum": ["fasta_zero_records@1"],
                    },
                    "metadata": {"type": "object"},
                },
                "required": ["sandbox_workspace_id", "path"],
                "additionalProperties": False,
            },
        ),
    )


def executor_hpc_workspace_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    workspace_id_schema = {
        "type": "object",
        "properties": {"workspace_id": {"type": "string"}},
        "required": ["workspace_id"],
        "additionalProperties": False,
    }
    return (
        ToolDescriptor(
            tool_name="hpc.workspace.request",
            description=(
                "Persist and provision one exact executor-owned HPC login workspace. "
                "This does not authorize or submit a scheduler job."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "target_profile_id": {"type": "string"},
                    "remote_workspace_generation": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "idempotency_key": {"type": "string"},
                    "absolute_deadline": {"type": "string"},
                },
                "required": [
                    "target_profile_id",
                    "remote_workspace_generation",
                    "idempotency_key",
                    "absolute_deadline",
                ],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="hpc.workspace.inspect",
            description=(
                "Read the owner-only native login locator and safe workspace facts."
            ),
            input_schema=workspace_id_schema,
        ),
        ToolDescriptor(
            tool_name="hpc.workspace.verify",
            description=(
                "Verify the exact protected remote root, runner receipt, independent "
                "Git clone, origin, and Git LFS availability before a formal boundary."
            ),
            input_schema=workspace_id_schema,
        ),
        ToolDescriptor(
            tool_name="hpc.workspace.sync_source",
            description=(
                "Project one exact private checkpoint or immutable published revision "
                "for agent-controlled native Git sync. This does not mutate the worktree."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "checkpoint_id": {"type": "string"},
                    "publication_id": {"type": "string"},
                },
                "required": ["workspace_id"],
                "oneOf": [
                    {
                        "required": ["checkpoint_id"],
                        "not": {"required": ["publication_id"]},
                    },
                    {
                        "required": ["publication_id"],
                        "not": {"required": ["checkpoint_id"]},
                    },
                ],
                "additionalProperties": False,
            },
        ),
    )


def sandbox_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_name="sandbox.file.list",
            description="List files in the executor persistent sandbox workspace without exposing Host paths.",
            input_schema={
                "type": "object",
                "properties": {
                    "sandbox_workspace_id": {"type": "string"},
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="sandbox.file.read",
            description="Read a bounded UTF-8 text page or binary digest summary from the executor sandbox workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "sandbox_workspace_id": {"type": "string"},
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 0, "maximum": 262144},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="sandbox.file.write",
            description="Atomically write a small UTF-8 text file under /workspace/src, /workspace/work, /workspace/output, or /workspace/logs.",
            input_schema={
                "type": "object",
                "properties": {
                    "sandbox_workspace_id": {"type": "string"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "create_dirs": {"type": "boolean"},
                    "expected_digest": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="sandbox.file.patch",
            description="Apply a single-file unified diff under the executor sandbox workspace with base digest concurrency control.",
            input_schema={
                "type": "object",
                "properties": {
                    "sandbox_workspace_id": {"type": "string"},
                    "path": {"type": "string"},
                    "base_digest": {"type": "string"},
                    "patch": {"type": "string"},
                },
                "required": ["path", "base_digest", "patch"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="sandbox.file.delete",
            description="Delete one regular file under an allowed executor sandbox workspace directory.",
            input_schema={
                "type": "object",
                "properties": {
                    "sandbox_workspace_id": {"type": "string"},
                    "path": {"type": "string"},
                    "expected_digest": {"type": "string"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="sandbox.exec",
            description=(
                "Run bounded direct argv only after the Host snapshots the entire "
                "non-empty /workspace/src tree. Every otherwise-valid invocation, "
                "including Python -c, package/signature inspection, and diagnostics, "
                "fails closed with source_snapshot_empty when that tree has no files. "
                "This is not a read-only environment-inspection shortcut; author "
                "explicit source first. No implicit shell (use bash -lc explicitly)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "sandbox_workspace_id": {"type": "string"},
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "cwd": {"type": "string"},
                    "timeout_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": EXEC_MAX_TIMEOUT_SECONDS,
                    },
                    "env": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        ),
    )


def agent_capsule_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_name="workspace.exec",
            description=(
                "Run one native argv in your exact generation-owned Git clone. "
                "The Host never auto-retries, changes endpoints, stages, commits, "
                "pushes, cleans, or promotes files. Ordinary credentialless network "
                "uses deployment reachability; request a Host credential only with "
                "an exact service, target, protocol, and audience."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 256,
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 3600,
                    },
                    "credential": {
                        "type": "object",
                        "properties": {
                            "service_id": {"type": "string"},
                            "target_id": {"type": "string"},
                            "protocol": {"type": "string"},
                            "audience": {"type": "string"},
                        },
                        "required": [
                            "service_id",
                            "target_id",
                            "protocol",
                            "audience",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="workspace.status",
            description=(
                "Observe the exact local HEAD/tree and clean, staged, unstaged, "
                "or untracked state of your generation-owned clone without "
                "projecting private paths or mutating Git state."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="workspace.checkpoint.verify",
            description=(
                "Read-only verify that an explicit private-ref create or "
                "fast-forward observation points to your declared commit/tree. "
                "This records owner-private checkpoint proof; it does not push, "
                "publish, send a handoff, launch a job, or finish a task."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "boundary": {
                        "type": "string",
                        "enum": [
                            "durable_checkpoint",
                            "publication",
                            "handoff",
                            "external_job",
                            "task_terminal",
                        ],
                    },
                    "workspace_generation": {"type": "integer", "minimum": 1},
                    "commit": {"type": "string"},
                    "tree": {"type": "string"},
                    "private_ref": {"type": "string"},
                    "remote_observation": {
                        "type": "object",
                        "properties": {
                            "service_id": {"type": "string"},
                            "repository_id": {"type": "string"},
                            "prior_commit": {"type": ["string", "null"]},
                            "advance_kind": {
                                "type": "string",
                                "enum": ["create", "fast_forward"],
                            },
                            "observed_at": {"type": "string"},
                        },
                        "required": [
                            "service_id",
                            "repository_id",
                            "prior_commit",
                            "advance_kind",
                            "observed_at",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "boundary",
                    "workspace_generation",
                    "commit",
                    "tree",
                    "private_ref",
                    "remote_observation",
                ],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="workspace.publish",
            description=(
                "Explicitly publish the exact clean whole-repository checkpoint "
                "through one Host-owned create-only immutable ref. The Host does "
                "not stage, commit, clean, rewrite, retry a possible effect, push "
                "upstream, merge, send a handoff, or finish a task."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "idempotency_key": {"type": "string"},
                    "workspace_id": {"type": "string"},
                    "workspace_generation": {"type": "integer", "minimum": 1},
                    "expected_head_commit": {"type": "string"},
                    "expected_tree": {"type": "string"},
                    "declared_base_commit": {"type": "string"},
                    "checkpoint_id": {"type": "string"},
                    "whole_repository": {"type": "boolean", "const": True},
                    "repository_binding_version": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "parent_publication_id": {"type": ["string", "null"]},
                    "supersedes_publication_id": {"type": ["string", "null"]},
                },
                "required": [
                    "idempotency_key",
                    "workspace_id",
                    "workspace_generation",
                    "expected_head_commit",
                    "expected_tree",
                    "declared_base_commit",
                    "checkpoint_id",
                    "whole_repository",
                    "repository_binding_version",
                ],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="workspace.publication.fetch_identity",
            description=(
                "Read the exact immutable ref, commit, tree, and manifest identity "
                "for an already materialized publication. Fetch, checkout, merge, "
                "rebase, and conflict strategy remain explicit agent actions."
            ),
            input_schema={
                "type": "object",
                "properties": {"publication_id": {"type": "string"}},
                "required": ["publication_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="workspace.publication.audit",
            description=(
                "Read-only compare canonical publications with their exact "
                "Host-owned immutable refs. This never scans private or historical "
                "refs and performs no repair, force-update, deletion, or fallback."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="workspace.publication.path_ref",
            description=(
                "Create a closed RevisionPathRef@1 for one exact path in an "
                "already materialized immutable publication."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "publication_id": {"type": "string"},
                    "path": {"type": "string"},
                    "ref_id": {"type": "string"},
                    "entry_kind": {
                        "type": "string",
                        "enum": ["file", "directory"],
                    },
                },
                "required": ["publication_id", "path", "ref_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="workspace.publication.verify_path_ref",
            description=(
                "Revalidate a complete RevisionPathRef@1 against canonical "
                "publication, path, Git object, and Git LFS identity."
            ),
            input_schema={
                "type": "object",
                "properties": {"revision_path_ref": {"type": "object"}},
                "required": ["revision_path_ref"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="workspace.publication.fetch_handoff",
            description=(
                "As the exact recipient, natively fetch one immutable publication "
                "from a bounded ProtocolFileHandoff@1 and verify every Git/Git LFS "
                "identity. This performs no checkout, merge, or task transition."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "handoff_id": {"type": "string"},
                    "publication_id": {"type": "string"},
                },
                "required": ["handoff_id", "publication_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="workspace.publication.index_research_file",
            description=(
                "Attach bounded research metadata to an exact published "
                "RevisionPathRef@1 without storing dossier or tool-result bytes."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "index_id": {"type": "string"},
                    "invocation_id": {"type": "string"},
                    "research_kind": {
                        "type": "string",
                        "enum": [
                            "source_snapshot",
                            "citations",
                            "notes",
                            "analysis",
                            "dossier",
                            "tool_result",
                        ],
                    },
                    "revision_path_ref": {"type": "object"},
                    "summary": {"type": "string"},
                },
                "required": [
                    "invocation_id",
                    "research_kind",
                    "revision_path_ref",
                ],
                "additionalProperties": False,
            },
        ),
    )


def world_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_name="world.inspect",
            description=(
                "Inspect structured session world facts for the current agent step, including task board, "
                "agents, inbox, runtime signals, artifacts, capabilities, controlled operations, approvals, "
                "outcomes, diagnostics, tool schemas, route policies, approval requirements, and input constraints. "
                "This tool returns facts and constraints only; it does not recommend next actions or decide task completion."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "session",
                                "tasks",
                                "agents",
                                "inbox",
                                "runtime_signals",
                                "artifacts",
                                "capabilities",
                                "operations",
                                "approvals",
                                "outcomes",
                                "diagnostics",
                                "affordances",
                            ],
                        },
                    },
                    "task_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "additionalProperties": False,
            },
        ),
    )


def failure_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_name="failure.get",
            description=(
                "Inspect one public-safe immutable failure observation, including "
                "typed effect certainty and deterministic likely causes."
            ),
            input_schema={
                "type": "object",
                "properties": {"failure_id": {"type": "string"}},
                "required": ["failure_id"],
                "additionalProperties": False,
            },
        ),
    )


def scientific_attempt_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    idempotency = {"type": "string", "minLength": 1}
    return (
        ToolDescriptor(
            tool_name="scientific.attempt.inspect",
            description=(
                "Inspect bounded scientific facts. Omit ids for a summary; provide "
                "attempt_id and selection_id for a stable occurrence page with "
                "compatible roles, current facts, issues, and readiness. It never "
                "chooses a scientific action."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "attempt_id": {"type": "string", "minLength": 1},
                    "selection_id": {"type": "string", "minLength": 1},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                    },
                    "cursor": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="attempt.create",
            description=(
                "Request one fresh scientific attempt from an existing durable "
                "authorization envelope after creating a canonical lane and binding "
                "the current task. The Host derives task, lane, campaign, workflow, "
                "scope, resources, effect classes, and private routes from canonical "
                "state, then finalizes the exact attempt after this writer turn retires. "
                "A successful request ends the current bounded turn without changing "
                "business task status; the Host resumes the teammate with canonical "
                "late-bound attempt facts."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "envelope_id": {"type": "string"},
                    "idempotency_key": idempotency,
                },
                "required": ["envelope_id", "idempotency_key"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="scientific.selection.begin",
            description=(
                "Start a CAS-protected selection revision over the complete "
                "Host-derived operation universe. The Host never auto-selects the "
                "latest or successful occurrence."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "attempt_id": {"type": "string"},
                    "expected_head_state_version": {
                        "type": ["integer", "null"],
                        "minimum": 0,
                    },
                    "parent_selection_id": {"type": ["string", "null"]},
                    "idempotency_key": idempotency,
                },
                "required": ["attempt_id", "idempotency_key"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="scientific.operation.disposition",
            description=(
                "Explicitly classify one occurrence as superseded, failed, or "
                "abandoned. Use scientific.operation.adopt for an adopted result. "
                "Known failures remain auditable; unknown effects cannot be hidden."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "selection_id": {"type": "string"},
                    "operation_id": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["superseded", "failed", "abandoned"],
                    },
                    "reason_code": {"type": "string"},
                    "replacement_operation_id": {"type": ["string", "null"]},
                    "idempotency_key": idempotency,
                },
                "required": [
                    "selection_id",
                    "operation_id",
                    "kind",
                    "reason_code",
                    "idempotency_key",
                ],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="scientific.operation.adopt",
            description=(
                "Atomically adopt one same-attempt terminal-known operation "
                "into a compatible workflow role. You choose the "
                "operation, role, and reason; the Host creates both canonical facts."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "selection_id": {"type": "string"},
                    "operation_id": {"type": "string"},
                    "workflow_role": {"type": "string"},
                    "reason_code": {"type": "string"},
                    "idempotency_key": idempotency,
                },
                "required": [
                    "selection_id",
                    "operation_id",
                    "workflow_role",
                    "reason_code",
                    "idempotency_key",
                ],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="scientific.artifact.materialize",
            description=(
                "Materialize sealed bytes from an adopted same-attempt result into "
                "another bound sandbox run through the Host artifact boundary. "
                "Shared paths or manual copies do not create adoption authority."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "selection_id": {"type": "string"},
                    "adoption_id": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "target_sandbox_run_id": {"type": "string"},
                    "target": {"type": "string"},
                    "idempotency_key": idempotency,
                },
                "required": [
                    "selection_id",
                    "adoption_id",
                    "source_artifact_id",
                    "target_sandbox_run_id",
                    "target",
                    "idempotency_key",
                ],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="scientific.selection.seal",
            description=(
                "Seal a complete selected chain only after every Host-derived "
                "occurrence is validly disposed and every adopted role verifies."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "selection_id": {"type": "string"},
                    "expected_universe_digest": {"type": "string"},
                    "idempotency_key": idempotency,
                },
                "required": [
                    "selection_id",
                    "expected_universe_digest",
                    "idempotency_key",
                ],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="scientific.attempt.close",
            description=(
                "As the canonical attempt task assignee, request Host finalization "
                "of the exact sealed selection without changing task status. "
                "Success ends this turn; Host finalizes only after the writer "
                "retires. Process the closure wake, then explicitly call "
                "task.finish(completed)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "attempt_id": {"type": "string"},
                    "selection_id": {"type": "string"},
                    "finalization_receipt_id": {"type": "string"},
                    "idempotency_key": idempotency,
                },
                "required": [
                    "attempt_id",
                    "selection_id",
                    "idempotency_key",
                ],
                "additionalProperties": False,
            },
        ),
    )


class _RuntimeDescriptorCollector:
    def __init__(self) -> None:
        self.runtimes: dict[str, ToolRuntime] = {}

    def register(self, tool_name: str, handler: Any) -> None:
        del tool_name, handler

    def register_runtime(self, runtime: ToolRuntime) -> None:
        tool_name = getattr(runtime, "tool_name", None)
        if isinstance(tool_name, str) and tool_name:
            self.runtimes[tool_name] = runtime


def _descriptor_step_context() -> AgentStepContext:
    return AgentStepContext(
        step_id="catalog_descriptor_projection",
        session_id="catalog",
        agent_id="catalog",
        actor_kind="catalog",
        role="catalog",
        call_index=0,
    )


def engine_tool_descriptors(
    engine_registry: EngineRegistry | None = None,
) -> tuple[ToolDescriptor, ...]:
    if engine_registry is None:
        return ()
    step_context = _descriptor_step_context()
    descriptors: list[ToolDescriptor] = []
    for engine in engine_registry.list_engines():
        collector = _RuntimeDescriptorCollector()
        engine.register_tools(collector)
        projected: set[str] = set()
        for tool_name in engine.descriptor.tool_names:
            runtime = collector.runtimes.get(tool_name)
            if runtime is None:
                continue
            spec = runtime.spec(step_context)
            descriptors.append(
                ToolDescriptor(
                    tool_name=spec.tool_name,
                    description=spec.description,
                    input_schema=spec.input_schema,
                )
            )
            projected.add(tool_name)
        for tool_name, runtime in collector.runtimes.items():
            if tool_name in projected:
                continue
            spec = runtime.spec(step_context)
            descriptors.append(
                ToolDescriptor(
                    tool_name=spec.tool_name,
                    description=spec.description,
                    input_schema=spec.input_schema,
                )
            )
    return tuple(descriptors)


def builtin_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        *failure_tool_descriptors(),
        *scientific_attempt_tool_descriptors(),
        ToolDescriptor(
            tool_name="task.create",
            description="Create a new task in the current session when the user asks for new work to be tracked.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "subject": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                    },
                    "kind": {"type": "string"},
                    "status": {"type": "string", "enum": ["todo", "in_progress"]},
                    "assigned_ref": {"type": ["string", "null"]},
                    "blocked_by": {"type": "array", "items": {"type": "string"}},
                    "failure_summary": {"type": ["string", "null"]},
                    "failure_ref": {"type": ["string", "null"]},
                },
                "required": ["subject"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.update",
            description=(
                "Edit an existing task's wording, priority, assignment, or non-terminal "
                "state. Use task.finish for completed, blocked, failed, or cancelled task exits."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "subject": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": ["todo", "in_progress"]},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                    },
                    "kind": {"type": "string"},
                    "assigned_ref": {"type": ["string", "null"]},
                    "blocked_by": {"type": "array", "items": {"type": "string"}},
                    "failure_summary": {"type": ["string", "null"]},
                    "failure_ref": {"type": ["string", "null"]},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.finish",
            description=(
                "Explicitly close the current task stage as completed, blocked, failed, "
                "or cancelled. A successful task.finish terminates the current agent turn."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["completed", "blocked", "failed", "cancelled"],
                    },
                    "summary": {"type": "string"},
                    "evidence_refs": task_finish_evidence_refs_schema(),
                    "failure_summary": {"type": ["string", "null"]},
                    "failure_ref": {"type": ["string", "null"]},
                    "blocked_reason": {"type": ["string", "null"]},
                    "recovery_hint": {"type": ["string", "null"]},
                    "next_owner": {
                        "type": ["string", "null"],
                        "enum": ["master", "user", "teammate", None],
                    },
                },
                "required": ["task_id", "status", "summary"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.get",
            description="Fetch one task by id before updating or reasoning about it.",
            input_schema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.list",
            description="List the current task board to inspect ready, blocked, and in-progress work.",
            input_schema={
                "type": "object",
                "properties": {"lane_id": {"type": "string"}},
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.next",
            description="Get the next ready task when selecting what to do next.",
            input_schema={
                "type": "object",
                "properties": {"lane_id": {"type": "string"}},
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.delegate",
            description=(
                "Delegate a concrete task to one internal teammate agent by queuing a runtime wakeup. "
                "agent_role selects capability; omit agent_ref to create a new teammate, or use agent_ref only for an existing canonical agent by id, handle, or nickname. "
                "workflow_refs is opt-in: omit it or pass [] for no workflow binding; otherwise pass an explicit subset of the caller's authorized workflow refs. "
                f"Valid teammate roles are {', '.join(TEAMMATE_ROLE_NAMES)}."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent_role": {"type": "string", "enum": list(TEAMMATE_ROLE_NAMES)},
                    "agent_ref": {"type": "string"},
                    "instructions": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "workflow_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["task_id", "agent_role"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="protocol.thread",
            description=(
                "Inspect one internal team protocol thread by correlation id, including small structured payloads "
                "and latest status, summary, task, and failure observation fields."
            ),
            input_schema={
                "type": "object",
                "properties": {"correlation_id": {"type": "string"}},
                "required": ["correlation_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="protocol.handoff.get",
            description=(
                "Read one bounded ProtocolFileHandoff@1 as an authorized participant, "
                "including exact revision/path refs and no file bytes."
            ),
            input_schema={
                "type": "object",
                "properties": {"handoff_id": {"type": "string"}},
                "required": ["handoff_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="protocol.send",
            description=(
                "Send a structured internal team protocol message to a teammate or the harness. "
                "This only persists the message and queues a wakeup signal; it does not run the recipient."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "recipient": {"type": "string"},
                    "recipient_kind": {
                        "type": "string",
                        "enum": ["agent", "harness", "user", "system"],
                    },
                    "sender": {"type": "string"},
                    "sender_kind": {
                        "type": "string",
                        "enum": ["agent", "harness", "user", "system"],
                    },
                    "message_type": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "lane_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["recipient", "correlation_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="lane.create",
            description="Create a lane when work needs an isolated execution context.",
            input_schema={
                "type": "object",
                "properties": {
                    "lane_id": {"type": "string"},
                    "name": {"type": "string"},
                    "cwd": {"type": "string"},
                    "branch_name": {"type": "string"},
                },
                "required": ["lane_id", "name", "cwd"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="lane.bind_task",
            description="Bind a task to an existing lane.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "lane_id": {"type": "string"},
                },
                "required": ["task_id", "lane_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="lane.list",
            description="List lanes and their assigned work.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
        *world_tool_descriptors(),
        *artifact_tool_descriptors(),
        *sandbox_tool_descriptors(),
        ToolDescriptor(
            tool_name="memory.compact",
            description="Write a compact summary for session, lane, or task context.",
            input_schema={
                "type": "object",
                "properties": {
                    "scope_kind": {
                        "type": "string",
                        "enum": ["session", "lane", "task"],
                    },
                    "scope_ref": {"type": "string"},
                    "task_id": {"type": "string"},
                    "lane_id": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="docs.search",
            description=(
                "Search DocumentRegistry knowledge documents, including controlled "
                "pipeline SDK and sandbox docs. Workflow manifests and workflow: "
                "selection refs belong to WorkflowRegistry and are not docs.search "
                "documents."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="docs.read",
            description=(
                "Read one DocumentRegistry knowledge document by doc_id or registered "
                "knowledge path, optionally requiring an exact version and digest. "
                "A selected workflow manifest is already loaded by its selection "
                "owner; do not pass its workflow: ref or .workflow.json path here."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "path": {"type": "string"},
                    "version": {"type": "string"},
                    "content_sha256": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
    )


def top_level_tool_descriptors(
    engine_registry: EngineRegistry | None = None,
) -> tuple[ToolDescriptor, ...]:
    del engine_registry
    return builtin_tool_descriptors()


_FILE_WORKSPACE_FORBIDDEN_TOOL_PREFIXES = (
    "artifact.",
    "artifacts.",
    "sandbox.file.",
    "hpc.stage_artifact",
    "hpc.fetch_outputs",
)


def file_workspace_candidate_tool_descriptors(
    *,
    executor: bool = False,
) -> tuple[ToolDescriptor, ...]:
    """Return the not-yet-public file-workspace candidate catalog.

    This deliberately does not mutate ``builtin_tool_descriptors`` or advance a
    public epoch.  The successor public-interface cutover consumes this closed
    projection after its own admission gate.
    """

    descriptors = (
        *builtin_tool_descriptors(),
        *agent_capsule_tool_descriptors(),
        *(executor_hpc_workspace_tool_descriptors() if executor else ()),
    )
    candidate = tuple(
        descriptor
        for descriptor in descriptors
        if not descriptor.tool_name.startswith(_FILE_WORKSPACE_FORBIDDEN_TOOL_PREFIXES)
    )
    names = tuple(descriptor.tool_name for descriptor in candidate)
    if len(names) != len(set(names)):
        raise ValueError("file-workspace candidate catalog contains duplicate tools")
    return candidate


def file_workspace_candidate_catalog_digest(*, executor: bool = False) -> str:
    payload = [
        {
            "tool_name": descriptor.tool_name,
            "description": descriptor.description,
            "input_schema": descriptor.input_schema,
        }
        for descriptor in file_workspace_candidate_tool_descriptors(
            executor=executor
        )
    ]
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ToolDescriptor",
    "artifact_tool_descriptors",
    "builtin_tool_descriptors",
    "engine_tool_descriptors",
    "executor_hpc_workspace_tool_descriptors",
    "failure_tool_descriptors",
    "file_workspace_candidate_tool_descriptors",
    "file_workspace_candidate_catalog_digest",
    "sandbox_tool_descriptors",
    "scientific_attempt_tool_descriptors",
    "top_level_tool_descriptors",
    "world_tool_descriptors",
]
