from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
import tempfile
import time
from typing import Any
from typing import Callable

from fastapi.testclient import TestClient
from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations as apply_v3_sqlite_migrations
from openzyme_core import connect_sqlite as connect_v3_sqlite
from openzyme_core import sandbox_image_record
from openzyme_core.sandbox_runtime import S12_ROUTE_POLICIES
from openzyme_core.sandbox_workspace import DEFAULT_SANDBOX_IMAGE_REF
from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_engines import EvidenceSynthesis
from openzyme_engines import EvidenceSynthesisItem
from openzyme_engines import ResearchBriefDraft as EngineResearchBriefDraft
from openzyme_engines import ResearchSourceItem
from openzyme_engines import ResearchSupervisorAction
from openzyme_engines import ResearchUnitDraft
from openzyme_engines import ResearchUnitPlan
from openzyme_engines import ExecutionOutcome
from openzyme_engines.execution import DeterministicBioDatabaseAdapter
from openzyme_engines.execution import ExecutionArtifactRef
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import get_settings
from openzyme_runtime import live_e2e_skip_reason
from openzyme_runtime import live_hpc_skip_reason
from openzyme_runtime import live_llm_skip_reason
from openzyme_runtime import live_tavily_skip_reason

from .app import HostApiDependencies
from .app import create_app
from .foundation import build_configured_foundation
from .foundation import build_local_eval_foundation
from .tracing import workflow_trace


FoundationBuilder = Callable[[], RuntimeFoundation]


def _message_role(message: object) -> str | None:
    if isinstance(message, dict):
        return None if message.get("role") is None else str(message["role"])
    message_type = type(message).__name__
    if message_type == "HumanMessage":
        return "user"
    if message_type == "AIMessage":
        return "assistant"
    if message_type == "ToolMessage":
        return "tool"
    return None


def _message_content(message: object) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _tool_message_name(message: object) -> str | None:
    if isinstance(message, dict):
        return None if message.get("name") is None else str(message["name"])
    return (
        None
        if getattr(message, "name", None) is None
        else str(getattr(message, "name"))
    )


def _tool_message_call_id(message: object) -> str | None:
    if isinstance(message, dict):
        return (
            None
            if message.get("tool_call_id") is None
            else str(message["tool_call_id"])
        )
    return (
        None
        if getattr(message, "tool_call_id", None) is None
        else str(getattr(message, "tool_call_id"))
    )


def _tool_message_payload(message: object) -> dict[str, object]:
    try:
        envelope = json.loads(_message_content(message))
    except json.JSONDecodeError:
        return {}
    payload = envelope.get("payload")
    return payload if isinstance(payload, dict) else {}


def _created_code_artifact_id(messages: list[object]) -> str | None:
    for message in reversed(messages):
        if _tool_message_name(message) != "artifact.create_text":
            continue
        payload = _tool_message_payload(message)
        artifact = payload.get("artifact")
        if isinstance(artifact, dict) and artifact.get("artifact_id"):
            return str(artifact["artifact_id"])
    return None


def _latest_tool_payload(messages: list[object], tool_name: str) -> dict[str, object] | None:
    for message in reversed(messages):
        if _tool_message_name(message) == tool_name:
            return _tool_message_payload(message)
    return None


def _source_artifact_ref_from_payload(payload: dict[str, object] | None) -> tuple[str, str] | None:
    if payload is None:
        return None
    artifact = payload.get("artifact")
    if not isinstance(artifact, dict):
        return None
    artifact_id = artifact.get("artifact_id")
    digest = payload.get("content_digest")
    if artifact_id is None or digest is None:
        return None
    return str(artifact_id), str(digest)


def _execution_start_payloads(messages: list[object]) -> list[dict[str, object]]:
    return [
        _tool_message_payload(message)
        for message in messages
        if _tool_message_name(message) == "execution.pipeline.start"
    ]


def _execution_start_records(messages: list[object]) -> list[dict[str, object]]:
    return [
        {
            "call_id": _tool_message_call_id(message),
            "payload": _tool_message_payload(message),
        }
        for message in messages
        if _tool_message_name(message) == "execution.pipeline.start"
    ]


def _execution_record_has_idempotency_marker(
    record: dict[str, object],
    *,
    call_id: str,
    marker: str,
) -> bool:
    if record.get("call_id") == call_id:
        return True
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return False
    invocation = payload.get("invocation")
    if not isinstance(invocation, dict):
        return False
    return marker in str(invocation.get("idempotency_key") or "")


def _focused_task_from_prompt(system_prompt: str) -> str:
    for line in system_prompt.splitlines():
        if line.startswith("Focused task: "):
            return line.removeprefix("Focused task: ").strip()
    return ""


class V3LocalEvalInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0
        self.workflow_calls = 0
        self.report_delegated = False

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del tools
        self.calls += 1
        if self.purpose == "deep_research_researcher":
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_eval_deep_research_search",
                            "name": "web.search",
                            "args": {
                                "query": "thermostable glycoside hydrolase xylan substrate evidence",
                                "topic": "enzyme design",
                                "max_results": 3,
                            },
                        }
                    ],
                }
            return {"content": "Source-backed enzyme design evidence collected.", "tool_calls": []}
        if self.purpose == "v3_teammate_loop:researcher":
            return self._researcher_response(system_prompt)
        if self.purpose == "v3_teammate_loop:executor":
            return self._executor_response(system_prompt, messages)
        if self.purpose == "v3_teammate_loop:reporter":
            return self._reporter_response(system_prompt)
        return self._master_response(system_prompt, messages)

    def _researcher_response(self, system_prompt: str) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_eval_research"
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_research_start",
                        "name": "deep_research.start",
                        "args": {
                            "task_id": task_id,
                            "brief": "Collect enzyme design evidence for thermostability, substrate scope, and assay constraints.",
                        },
                    }
                ],
            }
        if self.calls == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_research_task_complete",
                        "name": "task.finish",
                        "args": {
                            "task_id": task_id,
                            "status": "completed",
                            "summary": "Research evidence collected.",
                        },
                    }
                ],
            }
        return {"content": "Research evidence collected.", "tool_calls": []}

    def _executor_response(
        self, system_prompt: str, messages: list[object]
    ) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_eval_execution"
        if any(
            _tool_message_name(message) in {"task.update", "task.finish"}
            for message in messages
        ):
            return {
                "content": "Execution approval resolved and artifacts captured.",
                "tool_calls": [],
            }
        if any(
            _tool_message_name(message) == "execution.pipeline.status"
            for message in messages
        ):
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_execution_task_complete",
                        "name": "task.finish",
                        "args": {
                            "task_id": task_id,
                            "status": "completed",
                            "summary": "Execution approval resolved and artifacts captured.",
                        },
                    }
                ],
            }
        code_artifact_id = _created_code_artifact_id(messages)
        if code_artifact_id is not None and not any(
            _tool_message_name(message) == "execution.pipeline.start"
            for message in messages
        ):
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_execution_start",
                        "name": "execution.pipeline.start",
                        "args": {
                            "task_id": task_id,
                            "code_artifact_id": code_artifact_id,
                            "inputs": {
                                "artifact_ids": ["art_eval_structure"],
                            },
                        },
                    }
                ],
            }
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_execution_source",
                        "name": "artifact.create_text",
                        "args": {
                            "filename": "fpocket_pipeline.py",
                            "content": (
                                "from openzyme_pipeline import artifacts, hpc, structure_tools\n"
                                "structure = artifacts.get('art_eval_structure')\n"
                                "ws = hpc.workspace('fpocket')\n"
                                "remote_structure = ws.stage_artifact(structure['artifact_id'], workspace_path='inputs/structure.pdb')\n"
                                "run = structure_tools.fpocket(structure=remote_structure, placement=ws, expected_outputs=[{'path': 'target_out', 'kind': 'directory', 'format': 'fpocket'}])\n"
                                "ws.fetch_outputs(run)\n"
                            ),
                        },
                    }
                ],
            }
        if "Existing execution pipeline invocation:" in system_prompt:
            invocation_id = (
                system_prompt.split("Existing execution pipeline invocation:", 1)[1]
                .split(".", 1)[0]
                .strip()
            )
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_execution_status",
                        "name": "execution.pipeline.status",
                        "args": {"invocation_id": invocation_id},
                    }
                ],
            }
        return {
            "content": "Execution started and is waiting for approval.",
            "tool_calls": [],
        }

    def _reporter_response(self, system_prompt: str) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_eval_report"
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_report_draft",
                        "name": "report_draft.update",
                        "args": {
                            "task_id": task_id,
                            "title": "V3 cutover evaluation report",
                            "summary": "Research, execution, and reporting completed through the V3 harness path.",
                            "status": "ready",
                            "markdown": (
                                "# V3 cutover evaluation report\n\n"
                                "The deterministic V3 eval completed research, execution, and final reporting."
                            ),
                        },
                    }
                ],
            }
        if self.calls == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_report_publish",
                        "name": "report.publish",
                        "args": {
                            "task_id": task_id,
                            "title": "V3 cutover evaluation report",
                            "summary": "Research, execution, and reporting completed through the V3 harness path.",
                            "stage_summary": "Deterministic cutover eval passed the V3 workspace path.",
                        },
                    }
                ],
            }
        if self.calls == 3:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_report_task_complete",
                        "name": "task.finish",
                        "args": {
                            "task_id": task_id,
                            "status": "completed",
                            "summary": "Report published.",
                        },
                    }
                ],
            }
        return {"content": "Report published.", "tool_calls": []}

    def _master_response(
        self, system_prompt: str, messages: list[object]
    ) -> dict[str, object]:
        latest_user_message = next(
            (
                _message_content(message)
                for message in reversed(messages)
                if _message_role(message) == "user"
            ),
            "",
        )
        focused_task = _focused_task_from_prompt(system_prompt)
        if (
            focused_task == "task_eval_research"
            and "completed task_id=task_eval_research" in system_prompt
        ):
            return {"content": "Research evidence collected.", "tool_calls": []}
        if (
            focused_task == "task_eval_execution"
            and "completed task_id=task_eval_execution" in system_prompt
        ):
            return {
                "content": "Execution artifacts were captured and are ready for reporting.",
                "tool_calls": [],
            }
        if (
            focused_task == "task_eval_report"
            and "completed task_id=task_eval_report" in system_prompt
        ):
            return {
                "content": "V3 evaluation report has been published.",
                "tool_calls": [],
            }
        self.workflow_calls += 1
        if self.workflow_calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_lane",
                        "name": "lane.create",
                        "args": {
                            "lane_id": "lane_eval_design",
                            "name": "design-eval",
                            "cwd": "/tmp/openzyme-v3-eval",
                            "branch_name": "eval/v3-cutover",
                        },
                    },
                    {
                        "id": "call_eval_research_task",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_eval_research",
                            "subject": "Extract design goals and evidence",
                            "description": "Extract design goals from the literature brief and collect supporting evidence.",
                            "kind": "research",
                            "priority": "high",
                        },
                    },
                    {
                        "id": "call_eval_bind_research",
                        "name": "lane.bind_task",
                        "args": {
                            "task_id": "task_eval_research",
                            "lane_id": "lane_eval_design",
                        },
                    },
                ],
            }
        if self.workflow_calls == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_delegate_research",
                        "name": "task.delegate",
                        "args": {
                            "task_id": "task_eval_research",
                            "agent_role": "researcher",
                            "instructions": "Extract the enzyme design goals and summarize supporting research evidence.",
                        },
                    },
                ],
            }
        if self.workflow_calls == 3:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_eval_execution_task",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_eval_execution",
                            "subject": "Run design execution check",
                            "description": "Run the deterministic execution check for the selected enzyme design scaffold.",
                            "kind": "execution",
                            "priority": "high",
                        },
                    },
                    {
                        "id": "call_eval_bind_execution",
                        "name": "lane.bind_task",
                        "args": {
                            "task_id": "task_eval_execution",
                            "lane_id": "lane_eval_design",
                        },
                    },
                    {
                        "id": "call_eval_delegate_execution",
                        "name": "task.delegate",
                        "args": {
                            "task_id": "task_eval_execution",
                            "agent_role": "executor",
                            "instructions": "Run the execution check and capture artifacts after approval.",
                        },
                    },
                ],
            }
        if "report" in latest_user_message.lower():
            if not self.report_delegated:
                self.report_delegated = True
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_eval_report_task",
                            "name": "task.create",
                            "args": {
                                "task_id": "task_eval_report",
                                "subject": "Draft final delivery report",
                                "description": "Draft and publish the final V3 design delivery report.",
                                "kind": "reporting",
                                "priority": "normal",
                            },
                        },
                        {
                            "id": "call_eval_bind_report",
                            "name": "lane.bind_task",
                            "args": {
                                "task_id": "task_eval_report",
                                "lane_id": "lane_eval_design",
                            },
                        },
                        {
                            "id": "call_eval_delegate_report",
                            "name": "task.delegate",
                            "args": {
                                "task_id": "task_eval_report",
                                "agent_role": "reporter",
                                "instructions": "Create and publish the final report draft from the workspace state.",
                            },
                        },
                    ],
                }
            return {
                "content": "V3 evaluation report has been published.",
                "tool_calls": [],
            }
        return {
            "content": "Execution is waiting for approval before final delivery.",
            "tool_calls": [],
        }


class V3LocalEvalModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, V3LocalEvalInvoker] = {}

    def create_structured_invoker(self, *, purpose: str) -> "V3LocalEvalStructuredInvoker":
        return V3LocalEvalStructuredInvoker(purpose)

    def create_tool_calling_invoker(self, *, purpose: str) -> V3LocalEvalInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = V3LocalEvalInvoker(purpose)
        return self.invokers[purpose]


class V3LocalEvalStructuredInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose

    def invoke_structured(
        self, *, schema: object, system_prompt: str, user_payload: dict[str, object]
    ) -> object:
        del system_prompt
        if schema is EngineResearchBriefDraft:
            return EngineResearchBriefDraft(
                research_brief=(
                    "Collect source-backed enzyme engineering evidence for thermostable "
                    "glycoside hydrolase scaffolds and soluble xylan turnover."
                )
            )
        if schema is ResearchSupervisorAction:
            if user_payload.get("unit_results"):
                return ResearchSupervisorAction(
                    action_kind="complete",
                    rationale="The eval research unit returned usable source-backed findings.",
                )
            return ResearchSupervisorAction(
                action_kind="conduct_research",
                rationale="Collect one focused source-backed evidence unit.",
                unit_plan=ResearchUnitPlan(
                    units=[
                        ResearchUnitDraft(
                            unit_id="eval_evidence",
                            topic="enzyme design evidence",
                            query="thermostable glycoside hydrolase xylan substrate evidence",
                            rationale="Support downstream execution and reporting.",
                        )
                    ],
                    synthesis_goal="Summarize evidence for the V3 eval design path.",
                ),
            )
        if schema is EvidenceSynthesis:
            return EvidenceSynthesis(
                summary="Source-backed enzyme design evidence supports the V3 eval scaffold path.",
                evidence_items=[
                    EvidenceSynthesisItem(
                        summary="Thermostable glycoside hydrolase evidence supports the scaffold direction.",
                        query="thermostable glycoside hydrolase xylan substrate evidence",
                        confidence_label="high",
                        sources=[
                            ResearchSourceItem(
                                title="Deterministic enzyme design source",
                                locator="https://example.org/eval-enzyme-design",
                                kind="web_page",
                                snippet="Thermostable scaffold evidence with xylan turnover context.",
                            )
                        ],
                    )
                ],
                unresolved_gaps=["Wet-lab validation remains outside the local eval."],
            )
        raise AssertionError(f"Unhandled eval structured schema {schema!r}")


AOX_HMM_ACCESSIONS = (
    "AAC72747.1",
    "KDQ24956.1",
    "9AVH_A",
    "XP_014653549.1",
    "KIS68002.1",
    "XP_003660923.1",
    "AMW87253.1",
    "AFP17823.1",
    "WP_190019735.1",
    "WP_138089821.1",
    "WP_176407597.1",
    "CAQ19343.1",
    "CAQ19344.1",
)

S15_AOX_HMM_SCENARIO_ID = "v3_aox_hmm_cutover_live_e2e"
S15_AOX_HMM_FIXTURE_SCENARIO_ID = "v3_aox_hmm_prompt_fixture"
S15_AOX_HMM_FIXED_PROMPT = (
    "Run AOX/HMM mining from only this prompt. Use these 13 AOX accessions: "
    + ", ".join(AOX_HMM_ACCESSIONS)
    + ". Build a reference HMM, search EBI HMMER refprot with bio.hmmer_search, "
    "filter hits to length 650-700 and HMM score >200, score with reference coordinate "
    "AAB57849.1 using activity score threshold 33.6, deduplicate at similarity threshold 0.85, "
    "and export normalized deliverables under aox_hmm/: AOX_ref21.fasta, target.fasta, "
    "AOX_ref.hmm, hits_raw.csv, hits_len650_700_200.csv, scored_ref_plus_hits.csv, "
    "AOX_candidates.fasta, AOX_candidates_cdhit85.fasta, nodes.csv, "
    "edges_similarity.csv, and execution_summary.json."
)
S15_AOX_HMM_FIXED_DELIVERABLES = {
    "aox_hmm/AOX_ref21.fasta",
    "aox_hmm/target.fasta",
    "aox_hmm/AOX_ref.hmm",
    "aox_hmm/hits_raw.csv",
    "aox_hmm/hits_len650_700_200.csv",
    "aox_hmm/scored_ref_plus_hits.csv",
    "aox_hmm/AOX_candidates.fasta",
    "aox_hmm/AOX_candidates_cdhit85.fasta",
    "aox_hmm/nodes.csv",
    "aox_hmm/edges_similarity.csv",
    "aox_hmm/execution_summary.json",
}
S15_AOX_HMM_OLD_DELIVERABLES = {
    "aox_hmm/filtered.fasta",
    "aox_hmm/filtered.csv",
    "aox_hmm/scoring.csv",
    "aox_hmm/candidates.fasta",
    "aox_hmm/candidates.csv",
    "aox_hmm/candidate_cdhit85.fasta",
}
S15_AOX_HMM_REQUIRED_CSV_COLUMNS = {
    "aox_hmm/hits_raw.csv": {"target", "uniprot_accession", "hmm_score", "evalue", "length"},
    "aox_hmm/hits_len650_700_200.csv": {
        "target",
        "uniprot_accession",
        "hmm_score",
        "evalue",
        "length",
        "sequence",
    },
    "aox_hmm/scored_ref_plus_hits.csv": {
        "id",
        "seq_score",
        "pass_rule",
        "activity_score",
        "reference_coordinate",
    },
    "aox_hmm/nodes.csv": {"node_id", "label", "score", "cluster_id"},
    "aox_hmm/edges_similarity.csv": {"source", "target", "similarity"},
}
S15_AOX_HMM_REQUIRED_SUMMARY_FIELDS = {
    "accession_count",
    "candidate_count",
    "length_filter",
    "hmm_score_threshold",
    "activity_score_threshold",
    "similarity_threshold",
    "hmmer_database",
    "provider_status",
    "tool_status",
    "warning_count",
    "artifact_ids",
    "normalized_final_deliverable_paths",
}


def _s15_aox_required_artifact_paths() -> set[str]:
    return set(S15_AOX_HMM_FIXED_DELIVERABLES)


def _s15_aox_missing_required_paths(artifact_paths: set[str]) -> list[str]:
    return sorted(S15_AOX_HMM_FIXED_DELIVERABLES - artifact_paths)


def _s15_aox_legacy_paths_present(artifact_paths: set[str]) -> list[str]:
    return sorted(S15_AOX_HMM_OLD_DELIVERABLES & artifact_paths)


def _s15_aox_validate_final_artifacts(
    artifact_paths: set[str],
    artifact_text_by_path: dict[str, str],
    artifact_metadata_by_path: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    missing = _s15_aox_missing_required_paths(artifact_paths)
    legacy_paths = _s15_aox_legacy_paths_present(artifact_paths)
    metadata_by_path = artifact_metadata_by_path or {}
    execution_summary: dict[str, object] = {}
    errors: list[dict[str, object]] = []
    if missing:
        errors.append({"error_code": "live_artifact_missing", "missing_paths": missing})
    for path in legacy_paths:
        errors.append({"error_code": "legacy_artifact_path_forbidden", "path": path})

    summary_text = artifact_text_by_path.get("aox_hmm/execution_summary.json", "")
    if "aox_hmm/execution_summary.json" in artifact_paths:
        try:
            loaded_summary = json.loads(summary_text)
        except json.JSONDecodeError:
            errors.append({"error_code": "invalid_json", "path": "aox_hmm/execution_summary.json"})
        else:
            if isinstance(loaded_summary, dict):
                execution_summary = loaded_summary
            else:
                errors.append({"error_code": "invalid_json", "path": "aox_hmm/execution_summary.json"})

    for path in sorted(S15_AOX_HMM_FIXED_DELIVERABLES):
        if path not in artifact_paths:
            continue
        text = artifact_text_by_path.get(path, "")
        if path == "aox_hmm/target.fasta" and not text.strip():
            warning_count = execution_summary.get("warning_count")
            if not isinstance(warning_count, int) or warning_count <= 0:
                errors.append({"error_code": "empty_target_warning_missing", "path": path})
        elif path.endswith(".fasta") and not text.lstrip().startswith(">"):
            errors.append({"error_code": "invalid_fasta", "path": path})
        if path in {"aox_hmm/AOX_candidates.fasta", "aox_hmm/AOX_candidates_cdhit85.fasta"} and not text.strip():
            candidate_count = execution_summary.get("candidate_count")
            if candidate_count not in {0, "0"}:
                errors.append({"error_code": "candidate_fasta_empty_inconsistent", "path": path})
        if path == "aox_hmm/AOX_ref.hmm" and not text.startswith("HMMER3"):
            errors.append({"error_code": "invalid_hmm", "path": path})
        if path == "aox_hmm/AOX_ref.hmm":
            metadata = metadata_by_path.get(path, {})
            for key in ("source_reference_fasta_artifact_id", "mafft_artifact_ids", "hmmbuild_artifact_ids"):
                if metadata.get(key) in (None, "", [], {}):
                    errors.append(
                        {
                            "error_code": "hmm_provenance_incomplete",
                            "path": path,
                            "missing_metadata": key,
                        }
                    )
        if path == "aox_hmm/AOX_ref21.fasta":
            metadata = metadata_by_path.get(path, {})
            if metadata.get("accession_count") != len(AOX_HMM_ACCESSIONS):
                errors.append(
                    {
                        "error_code": "invalid_accession_count",
                        "path": path,
                        "accession_count": metadata.get("accession_count"),
                    }
                )
            if metadata.get("provider_request_ids") in (None, "", [], {}):
                errors.append(
                    {
                        "error_code": "provider_provenance_incomplete",
                        "path": path,
                        "missing_metadata": "provider_request_ids",
                    }
                )
        required_columns = S15_AOX_HMM_REQUIRED_CSV_COLUMNS.get(path)
        if required_columns:
            header = set(text.splitlines()[0].split(",")) if text.splitlines() else set()
            missing_columns = sorted(required_columns - header)
            if missing_columns:
                errors.append(
                    {
                        "error_code": "invalid_csv_columns",
                        "path": path,
                        "missing_columns": missing_columns,
                    }
                )
        if path == "aox_hmm/execution_summary.json":
            if not execution_summary:
                continue
            missing_fields = sorted(S15_AOX_HMM_REQUIRED_SUMMARY_FIELDS - set(execution_summary))
            if missing_fields:
                errors.append(
                    {
                        "error_code": "invalid_execution_summary",
                        "path": path,
                        "missing_fields": missing_fields,
                    }
                )
            expected_values = {
                "accession_count": len(AOX_HMM_ACCESSIONS),
                "length_filter": [650, 700],
                "hmm_score_threshold": 200,
                "activity_score_threshold": 33.6,
                "similarity_threshold": 0.85,
                "hmmer_database": "refprot",
            }
            for key, expected in expected_values.items():
                if execution_summary.get(key) != expected:
                    errors.append(
                        {
                            "error_code": "invalid_execution_summary_value",
                            "path": path,
                            "field": key,
                            "expected": expected,
                            "actual": execution_summary.get(key),
                        }
                    )
            if sorted(execution_summary.get("normalized_final_deliverable_paths") or []) != sorted(
                S15_AOX_HMM_FIXED_DELIVERABLES
            ):
                errors.append(
                    {
                        "error_code": "invalid_normalized_final_deliverable_paths",
                        "path": path,
                    }
                )
            if not isinstance(execution_summary.get("artifact_ids"), list) or not execution_summary.get("artifact_ids"):
                errors.append({"error_code": "invalid_artifact_ids", "path": path})
            if not execution_summary.get("provider_status") or not execution_summary.get("tool_status"):
                errors.append({"error_code": "invalid_execution_status_summary", "path": path})

    return {
        "passed": not errors,
        "missing_paths": missing,
        "legacy_paths": legacy_paths,
        "errors": errors,
    }


S15_ROUTE_POLICY_IDS = {
    "bio.ncbi_fetch_proteins": "bio.ncbi_fetch_proteins.provider:v1",
    "bio.uniprot_fetch": "bio.uniprot_fetch.provider:v1",
    "bio.hmmer_search": "bio.hmmer_search.provider:v1",
    "bio_tools.cdhit": "bio_tools.cdhit.hpc:v1",
    "bio_tools.mafft": "bio_tools.mafft.hpc:v1",
    "bio_tools.hmmbuild": "bio_tools.hmmbuild.hpc:v1",
    "bio_tools.hmmalign": "bio_tools.hmmalign.hpc:v1",
    "bio_tools.hmmer_search_cli": "bio_tools.hmmer_search_cli.disabled:v1",
}


def _s15_prerequisite_entry(
    *,
    name: str,
    status: str,
    required: bool = True,
    error_code: str | None = None,
    hint: str | None = None,
    **extra: object,
) -> dict[str, object]:
    entry: dict[str, object] = {"name": name, "status": status, "required": required}
    if error_code is not None:
        entry["error_code"] = error_code
    if hint is not None:
        entry["hint"] = hint
    entry.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
    return entry


def _s15_route_policy_prerequisite(
    *,
    name: str,
    route_policy_id: str,
    required: bool = True,
    forced_missing_hint: str | None = None,
) -> dict[str, object]:
    policy = S12_ROUTE_POLICIES.get(route_policy_id)
    if policy is None:
        return _s15_prerequisite_entry(
            name=name,
            status="prerequisite_missing",
            required=required,
            error_code="live_prerequisite_missing",
            hint=f"Route policy {route_policy_id!r} is not registered.",
            route_policy_id=route_policy_id,
        )
    if forced_missing_hint is not None:
        return _s15_prerequisite_entry(
            name=name,
            status="prerequisite_missing",
            required=required,
            error_code="live_prerequisite_missing",
            hint=forced_missing_hint,
            route_policy_id=route_policy_id,
            selected_backend=policy.get("selected_backend"),
            route_reason=policy.get("route_reason"),
            provider_config_digest=policy.get("provider_config_digest"),
            runtime_packaging_id=policy.get("runtime_packaging_id"),
            toolchain_id=policy.get("toolchain_id"),
            evidence_ref=policy.get("evidence_ref"),
        )
    status = str(policy.get("status") or "prerequisite_missing")
    if status == "ok":
        return _s15_prerequisite_entry(
            name=name,
            status="ok",
            required=required,
            route_policy_id=route_policy_id,
            selected_backend=policy.get("selected_backend"),
            route_reason=policy.get("route_reason"),
            provider_config_digest=policy.get("provider_config_digest"),
            runtime_packaging_id=policy.get("runtime_packaging_id"),
            toolchain_id=policy.get("toolchain_id"),
            evidence_ref=policy.get("evidence_ref"),
            parameter_inventory_ref=policy.get("parameter_inventory_ref"),
        )
    error_code = str(policy.get("error_code") or "live_prerequisite_missing")
    return _s15_prerequisite_entry(
        name=name,
        status=status,
        required=required,
        error_code=error_code,
        hint=str(policy.get("route_reason") or error_code),
        route_policy_id=route_policy_id,
        selected_backend=policy.get("selected_backend"),
        route_reason=policy.get("route_reason"),
        runtime_packaging_id=policy.get("runtime_packaging_id"),
        toolchain_id=policy.get("toolchain_id"),
        evidence_ref=policy.get("evidence_ref"),
    )


def _s15_sandbox_image_prerequisite(
    *,
    image_ref: str = DEFAULT_SANDBOX_IMAGE_REF,
    podman_binary: str = "podman",
) -> dict[str, object]:
    podman_path = shutil.which(podman_binary)
    if podman_path is None:
        return _s15_prerequisite_entry(
            name="sandbox_image",
            status="prerequisite_missing",
            error_code="sandbox_image_missing",
            hint="Install rootless podman and register the configured sandbox image before S15 live AOX/HMM.",
            image_ref=image_ref,
        )
    try:
        rootless = subprocess.run(
            [podman_binary, "info", "--format", "{{.Host.Security.Rootless}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _s15_prerequisite_entry(
            name="sandbox_image",
            status="prerequisite_missing",
            error_code="sandbox_image_missing",
            hint=f"Podman rootless preflight failed: {exc}",
            image_ref=image_ref,
        )
    if rootless.returncode != 0 or rootless.stdout.strip() != "true":
        detail = rootless.stderr.strip() or rootless.stdout.strip() or "rootless podman is not available"
        return _s15_prerequisite_entry(
            name="sandbox_image",
            status="prerequisite_missing",
            error_code="sandbox_image_missing",
            hint=f"Podman rootless preflight failed: {detail}",
            image_ref=image_ref,
        )
    try:
        image = subprocess.run(
            [podman_binary, "image", "exists", image_ref],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _s15_prerequisite_entry(
            name="sandbox_image",
            status="prerequisite_missing",
            error_code="sandbox_image_missing",
            hint=f"Sandbox image preflight failed: {exc}",
            image_ref=image_ref,
        )
    if image.returncode != 0:
        return _s15_prerequisite_entry(
            name="sandbox_image",
            status="prerequisite_missing",
            error_code="sandbox_image_missing",
            hint=(
                f"Sandbox image {image_ref!r} is not present; run "
                "`uv run python -m openzyme_pipeline.sandbox_image build`."
            ),
            image_ref=image_ref,
        )
    try:
        inspect = subprocess.run(
            [podman_binary, "image", "inspect", image_ref, "--format", "{{.Id}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _s15_prerequisite_entry(
            name="sandbox_image",
            status="prerequisite_missing",
            error_code="sandbox_image_missing",
            hint=f"Sandbox image digest inspection failed: {exc}",
            image_ref=image_ref,
        )
    image_digest = inspect.stdout.strip()
    if inspect.returncode != 0 or not image_digest:
        detail = inspect.stderr.strip() or inspect.stdout.strip() or "image digest is empty"
        return _s15_prerequisite_entry(
            name="sandbox_image",
            status="prerequisite_missing",
            error_code="sandbox_image_missing",
            hint=f"Sandbox image digest inspection failed: {detail}",
            image_ref=image_ref,
        )
    if not image_digest.startswith("sha256:"):
        image_digest = f"sha256:{image_digest}"
    return _s15_prerequisite_entry(
        name="sandbox_image",
        status="ok",
        image_ref=image_ref,
        image_digest=image_digest,
        podman_binary=podman_path,
        selected_backend="podman",
        evidence_ref="podman image inspect",
        cutover_grade="@" in image_ref,
    )


def _s15_bootstrap_live_sandbox_image(
    repositories: CoreRepositories,
    prerequisite_report: dict[str, object],
) -> None:
    checks = prerequisite_report.get("checks")
    if not isinstance(checks, list):
        return
    image_check = next(
        (
            check
            for check in checks
            if isinstance(check, dict) and check.get("name") == "sandbox_image"
        ),
        None,
    )
    if not isinstance(image_check, dict) or image_check.get("status") != "ok":
        return
    image_ref = str(image_check.get("image_ref") or DEFAULT_SANDBOX_IMAGE_REF)
    image_digest = image_check.get("image_digest")
    if not image_digest:
        return
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref=image_ref,
            image_digest=str(image_digest),
        )
    )


def _s15_live_prerequisite_report() -> dict[str, object]:
    settings = get_settings()
    checks: list[dict[str, object]] = []
    e2e_reason = live_e2e_skip_reason(settings)
    checks.append(
        _s15_prerequisite_entry(
            name="live_e2e",
            status="ok" if e2e_reason is None else "prerequisite_missing",
            error_code=None if e2e_reason is None else "live_prerequisite_missing",
            hint=e2e_reason,
        )
    )
    llm_reason = live_llm_skip_reason(settings)
    checks.append(
        _s15_prerequisite_entry(
            name="llm",
            status="ok" if llm_reason is None else "prerequisite_missing",
            error_code=None if llm_reason is None else "live_prerequisite_missing",
            hint=llm_reason,
        )
    )
    tavily_reason = live_tavily_skip_reason(settings)
    checks.append(
        _s15_prerequisite_entry(
            name="tavily",
            status="ok" if tavily_reason is None else "prerequisite_missing",
            error_code=None if tavily_reason is None else "live_prerequisite_missing",
            hint=tavily_reason,
        )
    )
    hpc_reason = live_hpc_skip_reason(settings)
    checks.append(
        _s15_prerequisite_entry(
            name="hpc_runner_config",
            status="ok" if hpc_reason is None else "prerequisite_missing",
            error_code=None if hpc_reason is None else "live_prerequisite_missing",
            hint=hpc_reason,
            selected_backend=settings.execution.backend,
            config_present=bool(settings.execution.hpc_runner_config),
        )
    )
    checks.append(_s15_sandbox_image_prerequisite())
    ncbi_identity_hint = None
    if not os.getenv("OPENZYME_NCBI_EMAIL") and not os.getenv("NCBI_EMAIL"):
        ncbi_identity_hint = "Set OPENZYME_NCBI_EMAIL or NCBI_EMAIL before live AOX/HMM."
    checks.append(
        _s15_prerequisite_entry(
            name="ncbi_identity",
            status="ok" if ncbi_identity_hint is None else "prerequisite_missing",
            error_code=None if ncbi_identity_hint is None else "live_prerequisite_missing",
            hint=ncbi_identity_hint,
        )
    )
    checks.extend(
        [
            _s15_route_policy_prerequisite(
                name="bio.ncbi_fetch_proteins",
                route_policy_id=S15_ROUTE_POLICY_IDS["bio.ncbi_fetch_proteins"],
                forced_missing_hint=ncbi_identity_hint,
            ),
            _s15_route_policy_prerequisite(
                name="bio.uniprot_fetch",
                route_policy_id=S15_ROUTE_POLICY_IDS["bio.uniprot_fetch"],
            ),
            _s15_route_policy_prerequisite(
                name="bio.hmmer_search_refprot",
                route_policy_id=S15_ROUTE_POLICY_IDS["bio.hmmer_search"],
            ),
            _s15_route_policy_prerequisite(
                name="bio_tools.cdhit",
                route_policy_id=S15_ROUTE_POLICY_IDS["bio_tools.cdhit"],
                forced_missing_hint=hpc_reason,
            ),
            _s15_route_policy_prerequisite(
                name="bio_tools.mafft",
                route_policy_id=S15_ROUTE_POLICY_IDS["bio_tools.mafft"],
                forced_missing_hint=hpc_reason,
            ),
            _s15_route_policy_prerequisite(
                name="bio_tools.hmmbuild",
                route_policy_id=S15_ROUTE_POLICY_IDS["bio_tools.hmmbuild"],
                forced_missing_hint=hpc_reason,
            ),
            _s15_route_policy_prerequisite(
                name="bio_tools.hmmalign",
                route_policy_id=S15_ROUTE_POLICY_IDS["bio_tools.hmmalign"],
                forced_missing_hint=hpc_reason,
            ),
            _s15_prerequisite_entry(
                name="staging_fetch_output_validation",
                status="ok" if hpc_reason is None else "prerequisite_missing",
                error_code=None if hpc_reason is None else "live_prerequisite_missing",
                hint=hpc_reason,
                evidence_ref="docs/v3/sessions/14-real-bio-tools-local-hpc-backends.md#测试验收",
            ),
            _s15_route_policy_prerequisite(
                name="bio_tools.hmmer_search_cli",
                route_policy_id=S15_ROUTE_POLICY_IDS["bio_tools.hmmer_search_cli"],
                required=False,
            ),
        ]
    )
    missing = [
        check
        for check in checks
        if check.get("required") is not False and check.get("status") != "ok"
    ]
    status = "ok" if not missing else "prerequisite_missing"
    return {
        "scenario_report_key": "s15_aox_hmm_current",
        "status": status,
        "required": [
            "llm",
            "tavily",
            "ncbi_identity",
            "uniprot_http",
            "ebi_hmmer_rest_refprot",
            "s14_hpc_bio_tools",
            "hpc_runner_config",
            "sandbox_image",
            "staging_fetch_output_validation",
        ],
        "missing": missing,
        "checks": checks,
        "selected_backend": {
            "bio.hmmer_search": "provider_http",
            "bio_tools.cdhit": "hpc",
            "bio_tools.mafft": "hpc",
            "bio_tools.hmmbuild": "hpc",
            "bio_tools.hmmalign": "hpc",
            "bio_tools.hmmer_search_cli": "disabled/unsupported_in_s14",
        },
        "route_policies": {
            name: S12_ROUTE_POLICIES.get(policy_id, {})
            for name, policy_id in S15_ROUTE_POLICY_IDS.items()
        },
    }


def _s15_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _s15_prompt_digest() -> str:
    return f"sha256:{hashlib.sha256(S15_AOX_HMM_FIXED_PROMPT.encode('utf-8')).hexdigest()}"


def _s15_config_snapshot_digest(
    *,
    scenario_id: str,
    prerequisite_report: dict[str, object],
) -> str:
    return _s15_digest(
        {
            "scenario_id": scenario_id,
            "prompt_digest": _s15_prompt_digest(),
            "prerequisite_report": prerequisite_report,
        }
    )


def _s15_non_empty_unique(values: list[str | None]) -> list[str]:
    return sorted({value for value in values if value})


def _s15_find_payload_values(payload: object, key: str) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for item_key, item_value in payload.items():
            if item_key == key and item_value not in (None, "", [], {}):
                values.append(str(item_value))
            else:
                values.extend(_s15_find_payload_values(item_value, key))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_s15_find_payload_values(item, key))
    return values


def _s15_final_answer(workspace: dict[str, Any]) -> str | None:
    for message in reversed(workspace.get("conversation") or []):
        if message.get("role") == "assistant" and message.get("content"):
            return str(message["content"])
    return None


def _s15_expected_output_paths(summary: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    items = summary.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("path"):
                paths.append(str(item["path"]))
    elif summary.get("path"):
        paths.append(str(summary["path"]))
    declared = summary.get("declared_outputs")
    if isinstance(declared, list):
        for item in declared:
            if isinstance(item, dict) and item.get("path"):
                paths.append(str(item["path"]))
    return sorted(set(paths))


def _s15_build_evidence_bundle(
    repositories: CoreRepositories,
    *,
    scenario_id: str,
    session_id: str,
    prompt: str,
    prerequisite_report: dict[str, object],
    workspace: dict[str, Any],
    artifacts: list[SessionArtifactRecord],
    required_paths: set[str],
    final_output_validation: dict[str, object],
) -> dict[str, object]:
    approvals = repositories.approvals.list_by_session(session_id)
    operations = repositories.controlled_operations.list_by_session(session_id)
    sandbox_workspaces = repositories.sandbox_workspaces.list_by_session(session_id)
    sandbox_runs = repositories.sandbox_runs.list_by_session(session_id)
    final_answer = _s15_final_answer(workspace)
    operation_trace: list[dict[str, object]] = []
    backend_run_ids: list[str | None] = []
    for operation in operations:
        backend_run_ids.extend(_s15_find_payload_values(operation.result_summary or {}, "backend_run_id"))
        backend_run_ids.extend(_s15_find_payload_values(operation.adapter_result_envelope or {}, "backend_run_id"))
        operation_trace.append(
            {
                "operation_id": operation.operation_id,
                "operation_digest": operation.operation_digest,
                "status": operation.status.value,
                "approval_id": operation.approval_id,
                "approval_state": operation.approval_state,
                "sandbox_workspace_id": operation.sandbox_workspace_id,
                "sandbox_run_id": operation.sandbox_run_id,
                "source_snapshot_artifact_id": operation.source_snapshot_artifact_id,
                "source_snapshot_digest": operation.source_snapshot_digest,
                "adapter_envelope_schema_version": operation.adapter_envelope_schema_version,
                "sdk_module": operation.sdk_module,
                "function_name": operation.function_name,
                "route_policy_id": operation.route_policy_id,
                "selected_backend": operation.selected_backend,
                "backend_category": operation.backend_category,
                "route_reason": operation.route_reason,
                "placement": operation.placement,
                "hpc_workspace_id": operation.hpc_workspace_id,
                "runtime_packaging_id": operation.runtime_packaging_id,
                "toolchain_id": operation.toolchain_id,
                "provider_config_digest": operation.provider_config_digest,
                "expected_output_paths": _s15_expected_output_paths(
                    operation.expected_outputs_summary or {}
                ),
                "stage_ref_count": len(operation.stage_refs),
                "planned_fetch_intent_digest": _s15_digest(operation.planned_fetch_intent or {}),
                "adapter_approval_envelope_digest": _s15_digest(
                    operation.adapter_approval_envelope or {}
                ),
                "adapter_result_envelope_digest": _s15_digest(
                    operation.adapter_result_envelope or {}
                ),
                "error_code": operation.error_code,
            }
        )
    source_snapshot_artifact_ids = _s15_non_empty_unique(
        [operation.source_snapshot_artifact_id for operation in operations]
        + [sandbox_run.source_snapshot_artifact_id for sandbox_run in sandbox_runs]
    )
    source_snapshot_digests = _s15_non_empty_unique(
        [operation.source_snapshot_digest for operation in operations]
        + [sandbox_run.source_tree_digest for sandbox_run in sandbox_runs]
    )
    sandbox_workspace_ids = [workspace_record.sandbox_workspace_id for workspace_record in sandbox_workspaces]
    evidence_bundle: dict[str, object] = {
        "fixed_prompt_digest": f"sha256:{hashlib.sha256(prompt.encode('utf-8')).hexdigest()}",
        "config_snapshot_digest": _s15_config_snapshot_digest(
            scenario_id=scenario_id,
            prerequisite_report=prerequisite_report,
        ),
        "session_id": session_id,
        "sandbox_workspace_id": sandbox_workspace_ids[0] if sandbox_workspace_ids else None,
        "sandbox_workspaces": [
            {
                "sandbox_workspace_id": sandbox_workspace.sandbox_workspace_id,
                "agent_member_id": sandbox_workspace.agent_member_id,
                "status": sandbox_workspace.status.value,
                "image_digest": sandbox_workspace.image_digest,
                "image_version": sandbox_workspace.image_version,
                "sandbox_protocol_version": sandbox_workspace.sandbox_protocol_version,
                "manifest_version": sandbox_workspace.manifest_version,
                "source_code_artifact_ids": list(sandbox_workspace.source_code_artifact_ids),
                "registered_artifact_ids": list(sandbox_workspace.registered_artifact_ids),
            }
            for sandbox_workspace in sandbox_workspaces
        ],
        "sandbox_image_digests": _s15_non_empty_unique(
            [sandbox_workspace.image_digest for sandbox_workspace in sandbox_workspaces]
        ),
        "sandbox_runs": [
            {
                "sandbox_run_id": sandbox_run.sandbox_run_id,
                "sandbox_workspace_id": sandbox_run.sandbox_workspace_id,
                "status": sandbox_run.status.value,
                "argv_digest": sandbox_run.argv_digest,
                "source_snapshot_artifact_id": sandbox_run.source_snapshot_artifact_id,
                "source_tree_digest": sandbox_run.source_tree_digest,
                "exit_code": sandbox_run.exit_code,
                "duration_ms": sandbox_run.duration_ms,
                "stdout_summary": sandbox_run.stdout_summary,
                "stderr_summary": sandbox_run.stderr_summary,
                "changed_files_summary": sandbox_run.changed_files_summary,
                "log_artifact_ref": sandbox_run.log_artifact_ref,
                "error_code": sandbox_run.error_code,
            }
            for sandbox_run in sandbox_runs
        ],
        "adapter_schema_versions": _s15_non_empty_unique(
            [operation.adapter_envelope_schema_version for operation in operations]
        ),
        "route_policy_ids": _s15_non_empty_unique([operation.route_policy_id for operation in operations]),
        "toolchain_ids": _s15_non_empty_unique([operation.toolchain_id for operation in operations]),
        "runtime_packaging_ids": _s15_non_empty_unique(
            [operation.runtime_packaging_id for operation in operations]
        ),
        "provider_config_digests": _s15_non_empty_unique(
            [operation.provider_config_digest for operation in operations]
        ),
        "selected_backends": _s15_non_empty_unique([operation.selected_backend for operation in operations]),
        "approval_ids": _s15_non_empty_unique([approval.approval_id for approval in approvals]),
        "approval_trace": [
            {
                "approval_id": approval.approval_id,
                "kind": approval.kind,
                "status": approval.status.value,
                "task_id": approval.task_id,
                "lane_id": approval.lane_id,
                "request_ref": approval.request_ref,
                "resolution_ref": approval.resolution_ref,
            }
            for approval in approvals
        ],
        "operation_trace": operation_trace,
        "operation_digests": _s15_non_empty_unique(
            [operation.operation_digest for operation in operations]
        ),
        "source_snapshot_artifact_ids": source_snapshot_artifact_ids,
        "source_snapshot_digests": source_snapshot_digests,
        "backend_run_ids": _s15_non_empty_unique(backend_run_ids),
        "registered_artifact_ids": [artifact.artifact_id for artifact in artifacts],
        "normalized_final_deliverable_paths": sorted(required_paths),
        "final_output_validation": final_output_validation,
        "warning_summary": [],
        "error_summary": [
            operation.error_code for operation in operations if operation.error_code
        ],
        "final_answer_available": final_answer is not None,
        "final_answer_digest": None if final_answer is None else _s15_digest({"content": final_answer}),
    }
    return evidence_bundle


def _s15_validate_evidence_bundle(evidence_bundle: dict[str, object]) -> dict[str, object]:
    required_non_empty = {
        "fixed_prompt_digest",
        "config_snapshot_digest",
        "session_id",
        "sandbox_workspace_id",
        "sandbox_image_digests",
        "adapter_schema_versions",
        "route_policy_ids",
        "toolchain_ids",
        "provider_config_digests",
        "approval_ids",
        "operation_trace",
        "operation_digests",
        "source_snapshot_artifact_ids",
        "source_snapshot_digests",
        "backend_run_ids",
        "registered_artifact_ids",
        "normalized_final_deliverable_paths",
        "final_answer_digest",
    }
    missing_fields = sorted(
        key for key in required_non_empty if evidence_bundle.get(key) in (None, "", [], {})
    )
    errors: list[dict[str, object]] = []
    if missing_fields:
        errors.append({"error_code": "live_evidence_incomplete", "missing_fields": missing_fields})
    operation_trace = evidence_bundle.get("operation_trace")
    if isinstance(operation_trace, list):
        for operation in operation_trace:
            if not isinstance(operation, dict):
                errors.append({"error_code": "live_evidence_incomplete", "invalid_operation_trace": True})
                continue
            for required_key in (
                "operation_id",
                "operation_digest",
                "approval_id",
                "sandbox_workspace_id",
                "source_snapshot_artifact_id",
                "source_snapshot_digest",
                "route_policy_id",
                "selected_backend",
            ):
                if operation.get(required_key) in (None, "", [], {}):
                    errors.append(
                        {
                            "error_code": "live_evidence_incomplete",
                            "operation_id": operation.get("operation_id"),
                            "missing_operation_field": required_key,
                        }
                    )
    else:
        errors.append({"error_code": "live_evidence_incomplete", "invalid_operation_trace": True})
    return {"passed": not errors, "missing_fields": missing_fields, "errors": errors}


def _s15_validate_live_product_path(
    evidence_bundle: dict[str, object],
    *,
    workspace: dict[str, Any],
    has_legacy_execution_pipeline: bool,
) -> dict[str, object]:
    errors: list[dict[str, object]] = []
    if has_legacy_execution_pipeline:
        errors.append({"error_code": "live_legacy_pipeline_forbidden"})
    if workspace.get("pending_approvals"):
        errors.append({"error_code": "live_approval_still_pending"})
    sandbox_runs = evidence_bundle.get("sandbox_runs")
    if not isinstance(sandbox_runs, list) or not sandbox_runs:
        errors.append({"error_code": "live_sandbox_exec_missing"})
    else:
        completed_runs = [
            run
            for run in sandbox_runs
            if isinstance(run, dict)
            and run.get("status") == "completed"
            and run.get("source_snapshot_artifact_id")
            and run.get("source_tree_digest")
        ]
        if not completed_runs:
            errors.append({"error_code": "live_sandbox_exec_missing_source_snapshot"})
    approval_trace = evidence_bundle.get("approval_trace")
    approved_ids = {
        item.get("approval_id")
        for item in approval_trace
        if isinstance(item, dict) and item.get("status") == "approved"
    } if isinstance(approval_trace, list) else set()
    if not approved_ids:
        errors.append({"error_code": "live_sdk_approval_missing"})
    operation_trace = evidence_bundle.get("operation_trace")
    if not isinstance(operation_trace, list) or not operation_trace:
        errors.append({"error_code": "live_sdk_operation_missing"})
    else:
        completed_operations = [
            operation
            for operation in operation_trace
            if isinstance(operation, dict)
            and operation.get("status") == "completed"
            and operation.get("approval_id") in approved_ids
        ]
        if not completed_operations:
            errors.append({"error_code": "live_sdk_operation_not_continued"})
    required_route_policy_ids = {
        S15_ROUTE_POLICY_IDS["bio.ncbi_fetch_proteins"],
        S15_ROUTE_POLICY_IDS["bio.uniprot_fetch"],
        S15_ROUTE_POLICY_IDS["bio.hmmer_search"],
        S15_ROUTE_POLICY_IDS["bio_tools.cdhit"],
        S15_ROUTE_POLICY_IDS["bio_tools.mafft"],
        S15_ROUTE_POLICY_IDS["bio_tools.hmmbuild"],
        S15_ROUTE_POLICY_IDS["bio_tools.hmmalign"],
    }
    observed_route_policy_ids = set(evidence_bundle.get("route_policy_ids") or [])
    missing_route_policy_ids = sorted(required_route_policy_ids - observed_route_policy_ids)
    if missing_route_policy_ids:
        errors.append(
            {
                "error_code": "live_evidence_incomplete",
                "missing_route_policy_ids": missing_route_policy_ids,
            }
        )
    return {"passed": not errors, "errors": errors}


def _s15_event_text_has_legacy_execution_pipeline(event_text: str) -> bool:
    return any(
        marker in event_text
        for marker in (
            '"tool_name":"execution.pipeline.start"',
            '"tool_name": "execution.pipeline.start"',
            '"name":"execution.pipeline.start"',
            '"name": "execution.pipeline.start"',
        )
    )


def _s15_inline_evidence_refs(
    *,
    scenario_id: str,
    session_id: str | None,
    status: str,
    prerequisite_report: dict[str, object],
    evidence_payload: dict[str, object] | None,
    safe_summary: dict[str, object],
) -> dict[str, object]:
    prompt_digest = _s15_prompt_digest()
    config_snapshot_digest = _s15_config_snapshot_digest(
        scenario_id=scenario_id,
        prerequisite_report=prerequisite_report,
    )
    prerequisite_report_digest = _s15_digest(prerequisite_report)
    evidence_bundle_digest: str | None = None
    if evidence_payload is not None:
        evidence_bundle_digest = _s15_digest(evidence_payload)
    return {
        "fixed_prompt_digest": prompt_digest,
        "config_snapshot_digest": config_snapshot_digest,
        "prerequisite_report_digest": prerequisite_report_digest,
        "evidence_bundle_digest": evidence_bundle_digest,
        "evidence_sealed": evidence_payload is not None,
        "safe_summary": safe_summary,
        "evidence_status": status,
    }


def _aox_hmm_draft_source() -> str:
    return (
        "from openzyme_pipeline import bio\n\n"
        f"AOX_ACCESSIONS = {list(AOX_HMM_ACCESSIONS)!r}\n\n"
        "reference = bio.ncbi_fetch_proteins(\n"
        "    accessions=AOX_ACCESSIONS,\n"
        "    output_dir='/workspace/output/bio/ncbi',\n"
        "    fields=['definition', 'organism'],\n"
        ")\n"
    )


def _aox_hmm_final_source() -> str:
    return f'''from pathlib import Path

from openzyme_pipeline import artifacts, bio, bio_tools, hpc


AOX_ACCESSIONS = {list(AOX_HMM_ACCESSIONS)!r}
OUTPUT = Path("/openzyme/output/aox_hmm")
OUTPUT.mkdir(parents=True, exist_ok=True)


def register_text(relative_path, content, *, kind="result", format=None, required_columns=None, metadata=None):
    target = OUTPUT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    artifact_metadata = dict(metadata or {{}})
    if required_columns:
        artifact_metadata["required_columns"] = list(required_columns)
    return artifacts.register(str(target), kind=kind, format=format, metadata=artifact_metadata)


def fasta_for(accessions):
    return "".join(f">{{accession}} candidate\\nMSEQUENCE{{index}}AOX\\n" for index, accession in enumerate(accessions, start=1))


reference = bio.ncbi_fetch_proteins(
    accessions=AOX_ACCESSIONS,
    output_dir="/workspace/output/bio/ncbi",
    fields=["definition", "organism", "length"],
)


def artifact_id_by_suffix(result, suffix):
    for artifact in result.get("artifacts", []):
        if str(artifact.get("relative_path", "")).endswith(suffix):
            return artifact["artifact_id"]
    raise RuntimeError(f"Missing expected artifact suffix: {{suffix}}")


reference_fasta_id = artifact_id_by_suffix(reference, "provider_parsed/proteins.fasta")
reference_metadata_id = artifact_id_by_suffix(reference, "provider_parsed/proteins.metadata.json")

ws = hpc.workspace("aox_hmm")


def stage(artifact_id, path):
    return ws.stage_artifact(artifact_id, workspace_path=path)


def fetch(run):
    return ws.fetch_outputs(run)


reference_fasta_remote = stage(reference_fasta_id, "inputs/reference.fasta")
reference_cdhit90 = fetch(bio_tools.cdhit(
    input_fasta=reference_fasta_remote,
    placement=ws,
    expected_outputs=[
        {{"path": "bio_tools/cdhit/clustered.fasta", "kind": "sequence", "format": "fasta"}},
        {{"path": "bio_tools/cdhit/clusters.csv", "kind": "result", "format": "csv"}},
    ],
    identity=0.9,
    mode="reference",
))
reference_cdhit90_remote = stage(reference_cdhit90["registered_artifact_ids"][0], "inputs/reference_cdhit90.fasta")
alignment = fetch(bio_tools.mafft(
    input_fasta=reference_cdhit90_remote,
    placement=ws,
    expected_outputs=[{{"path": "bio_tools/mafft/alignment.fasta", "kind": "sequence", "format": "fasta"}}],
))
alignment_remote = stage(alignment["registered_artifact_ids"][0], "inputs/alignment.fasta")
hmm = fetch(bio_tools.hmmbuild(
    alignment=alignment_remote,
    placement=ws,
    expected_outputs=[{{"path": "bio_tools/hmmbuild/model.hmm", "kind": "result", "format": "hmm"}}],
))
hmm_remote = stage(hmm["registered_artifact_ids"][0], "inputs/model.hmm")
hmmalign = fetch(bio_tools.hmmalign(
    hmm=hmm_remote,
    fasta=reference_fasta_remote,
    placement=ws,
    expected_outputs=[{{"path": "bio_tools/hmmalign/aligned.fasta", "kind": "sequence", "format": "fasta"}}],
))
hmmer_provider = bio.hmmer_search(
    hmm_artifact_id=hmm["registered_artifact_ids"][0],
    database="refprot",
    output_dir="/workspace/output/bio/hmmer",
    params={{"evalue": "1e-20", "query": "aox"}},
)
candidate_cdhit85 = fetch(bio_tools.cdhit(
    input_fasta=reference_fasta_remote,
    placement=ws,
    expected_outputs=[
        {{"path": "bio_tools/cdhit/clustered.fasta", "kind": "sequence", "format": "fasta"}},
        {{"path": "bio_tools/cdhit/clusters.csv", "kind": "result", "format": "csv"}},
    ],
    identity=0.85,
    mode="candidate",
))

candidates = AOX_ACCESSIONS[:5]
hits_raw_rows = ["target,uniprot_accession,hmm_score,evalue,length"]
hits_filtered_rows = ["target,uniprot_accession,hmm_score,evalue,length,sequence"]
scoring_rows = ["id,seq_score,pass_rule,activity_score,reference_coordinate"]
nodes = ["node_id,label,score,cluster_id"]
edges = ["source,target,similarity"]
for index, accession in enumerate(candidates, start=1):
    hmm_score = 240 - index
    seq_score = 40 - index
    sequence = f"MSEQUENCE{{index}}AOX"
    hits_raw_rows.append(f"target_{{index}},{{accession}},{{hmm_score}},1e-{{20 + index}},{{650 + index}}")
    hits_filtered_rows.append(f"target_{{index}},{{accession}},{{hmm_score}},1e-{{20 + index}},{{650 + index}},{{sequence}}")
    scoring_rows.append(f"{{accession}},{{seq_score}},true,{{seq_score}},AAB57849.1")
    nodes.append(f"{{accession}},candidate {{index}},{{seq_score}},cluster_1")
for left, right in zip(candidates, candidates[1:]):
    edges.append(f"{{left}},{{right}},0.91")

reference_fasta = register_text(
    "AOX_ref21.fasta",
    fasta_for(AOX_ACCESSIONS),
    kind="sequence",
    format="fasta",
    metadata={{"accession_count": len(AOX_ACCESSIONS), "provider_request_ids": reference.get("artifact_ids", [])}},
)
target_fasta = register_text(
    "target.fasta",
    fasta_for(candidates),
    kind="sequence",
    format="fasta",
    metadata={{"warning_policy": "empty_target_requires_structured_warning"}},
)
reference_hmm = register_text(
    "AOX_ref.hmm",
    "HMMER3/f [aox_ref]\\nNAME AOX_ref\\n//\\n",
    format="hmm",
    metadata={{
        "source_reference_fasta_artifact_id": reference_fasta["artifact_id"],
        "mafft_artifact_ids": alignment["registered_artifact_ids"],
        "hmmbuild_artifact_ids": hmm["registered_artifact_ids"],
    }},
)
hits_raw_csv = register_text(
    "hits_raw.csv",
    "\\n".join(hits_raw_rows) + "\\n",
    format="csv",
    required_columns=["target", "uniprot_accession", "hmm_score", "evalue", "length"],
)
hits_filtered_csv = register_text(
    "hits_len650_700_200.csv",
    "\\n".join(hits_filtered_rows) + "\\n",
    format="csv",
    required_columns=["target", "uniprot_accession", "hmm_score", "evalue", "length", "sequence"],
)
scored_csv = register_text(
    "scored_ref_plus_hits.csv",
    "\\n".join(scoring_rows) + "\\n",
    format="csv",
    required_columns=["id", "seq_score", "pass_rule"],
)
candidate_fasta = register_text(
    "AOX_candidates.fasta",
    fasta_for(candidates[:3]),
    kind="sequence",
    format="fasta",
    metadata={{"activity_score_threshold": 33.6}},
)
candidate_cdhit85_fasta = register_text(
    "AOX_candidates_cdhit85.fasta",
    fasta_for(candidates[:3]),
    kind="sequence",
    format="fasta",
    metadata={{
        "tool_name": "cd-hit",
        "identity": 0.85,
        "source_operation_artifact_ids": candidate_cdhit85["registered_artifact_ids"],
    }},
)
nodes_csv = register_text(
    "nodes.csv",
    "\\n".join(nodes) + "\\n",
    format="csv",
    required_columns=["node_id", "label", "score", "cluster_id"],
)
edges_csv = register_text(
    "edges_similarity.csv",
    "\\n".join(edges) + "\\n",
    format="csv",
    required_columns=["source", "target", "similarity"],
)
summary = {{
    "accession_count": len(AOX_ACCESSIONS),
    "candidate_count": len(candidates),
    "length_filter": [650, 700],
    "hmm_score_threshold": 200,
    "activity_score_threshold": 33.6,
    "similarity_threshold": 0.85,
    "hmmer_database": "refprot",
    "provider_status": "ok",
    "tool_status": "ok",
    "warning_count": 0,
    "reference_fasta_artifact_id": reference_fasta_id,
    "reference_metadata_artifact_id": reference_metadata_id,
    "cdhit90_artifact_ids": reference_cdhit90["registered_artifact_ids"],
    "alignment_artifact_ids": alignment["registered_artifact_ids"],
    "hmm_artifact_ids": hmm["registered_artifact_ids"],
    "hmmalign_artifact_ids": hmmalign["registered_artifact_ids"],
    "hmmer_provider_artifact_ids": hmmer_provider["artifact_ids"],
    "candidate_cdhit85_artifact_ids": candidate_cdhit85["registered_artifact_ids"],
    "derived_artifact_ids": [
        reference_fasta["artifact_id"],
        target_fasta["artifact_id"],
        reference_hmm["artifact_id"],
        hits_raw_csv["artifact_id"],
        hits_filtered_csv["artifact_id"],
        scored_csv["artifact_id"],
        candidate_fasta["artifact_id"],
        candidate_cdhit85_fasta["artifact_id"],
        nodes_csv["artifact_id"],
        edges_csv["artifact_id"],
    ],
    "artifact_ids": [],
    "normalized_final_deliverable_paths": [
        "aox_hmm/AOX_ref21.fasta",
        "aox_hmm/target.fasta",
        "aox_hmm/AOX_ref.hmm",
        "aox_hmm/hits_raw.csv",
        "aox_hmm/hits_len650_700_200.csv",
        "aox_hmm/scored_ref_plus_hits.csv",
        "aox_hmm/AOX_candidates.fasta",
        "aox_hmm/AOX_candidates_cdhit85.fasta",
        "aox_hmm/nodes.csv",
        "aox_hmm/edges_similarity.csv",
        "aox_hmm/execution_summary.json",
    ],
}}
summary["artifact_ids"] = list(summary["derived_artifact_ids"]) + [summary["execution_summary_artifact_id"]] if "execution_summary_artifact_id" in summary else list(summary["derived_artifact_ids"])
register_text(
    "execution_summary.json",
    __import__("json").dumps(summary, sort_keys=True, indent=2) + "\\n",
    format="json",
    metadata={{"candidate_count": len(candidates), "hmmer_database": "refprot"}},
)
'''


class V3AOXHMMEvalInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0
        self.workflow_calls = 0
        self._patched_source_ref: tuple[str, str] | None = None

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del tools
        self.calls += 1
        if self.purpose == "v3_teammate_loop:executor":
            return self._executor_response(system_prompt, messages)
        return self._master_response(system_prompt, messages)

    def _executor_response(self, system_prompt: str, messages: list[object]) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_aox_hmm_execution"
        if any(
            _tool_message_name(message) in {"task.update", "task.finish"}
            for message in messages
        ):
            return {
                "content": "AOX/HMM execution completed with candidate artifacts and provenance.",
                "tool_calls": [],
            }
        created_ref = _source_artifact_ref_from_payload(_latest_tool_payload(messages, "artifact.create_text"))
        patched_ref = _source_artifact_ref_from_payload(_latest_tool_payload(messages, "artifact.patch_text"))
        if patched_ref is not None:
            self._patched_source_ref = patched_ref
        diffed = any(_tool_message_name(message) == "artifact.diff_text" for message in messages)

        if self.calls >= 8:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_task_complete",
                        "name": "task.finish",
                        "args": {
                            "task_id": task_id,
                            "status": "completed",
                            "summary": "AOX/HMM execution completed with candidate artifacts and provenance.",
                        },
                    }
                ],
            }
        if self.calls in {5, 7} and "Existing execution pipeline invocation:" in system_prompt:
            invocation_id = (
                system_prompt.split("Existing execution pipeline invocation:", 1)[1]
                .split(".", 1)[0]
                .strip()
            )
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_execution_status",
                        "name": "execution.pipeline.status",
                        "args": {"invocation_id": invocation_id},
                    }
                ],
            }
        if self.calls >= 6 and self._patched_source_ref is not None:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_execute",
                        "name": "execution.pipeline.start",
                        "args": {
                            "task_id": task_id,
                            "code_artifact_id": self._patched_source_ref[0],
                            "inputs": {
                                "approval_policy": "single_plan",
                                "expected_outputs": [
                                    {"path": path}
                                    for path in sorted(S15_AOX_HMM_FIXED_DELIVERABLES)
                                ],
                            },
                        },
                    }
                ],
            }
        if patched_ref is not None and diffed:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_dry_run",
                        "name": "execution.pipeline.start",
                        "args": {
                            "task_id": task_id,
                            "code_artifact_id": patched_ref[0],
                            "inputs": {
                                "approval_policy": "single_plan",
                                "expected_outputs": [
                                    {"path": path}
                                    for path in sorted(S15_AOX_HMM_FIXED_DELIVERABLES)
                                ],
                            },
                            "dry_run": True,
                        },
                    }
                ],
            }
        if patched_ref is not None and created_ref is not None and not diffed:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_diff",
                        "name": "artifact.diff_text",
                        "args": {
                            "base_artifact_id": created_ref[0],
                            "target_artifact_id": patched_ref[0],
                        },
                    }
                ],
            }
        if created_ref is not None and patched_ref is None:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_patch_source",
                        "name": "artifact.patch_text",
                        "args": {
                            "base_artifact_id": created_ref[0],
                            "base_content_digest": created_ref[1],
                            "content": _aox_hmm_final_source(),
                        },
                    }
                ],
            }
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_aox_create_source",
                    "name": "artifact.create_text",
                    "args": {
                        "filename": "aox_hmm_pipeline.py",
                        "title": "AOX/HMM mining pipeline",
                        "content": _aox_hmm_draft_source(),
                    },
                }
            ],
        }

    def _master_response(self, system_prompt: str, messages: list[object]) -> dict[str, object]:
        del messages
        focused_task = _focused_task_from_prompt(system_prompt)
        if (
            focused_task == "task_aox_hmm_execution"
            and "completed task_id=task_aox_hmm_execution" in system_prompt
        ):
            return {
                "content": (
                    "AOX/HMM mining completed. The workspace contains reference FASTA and metadata, "
                    "CD-HIT/MAFFT/HMMER outputs, filtered and scored candidates, nodes/edges CSV, "
                    "and an execution summary with candidate_count=5."
                ),
                "tool_calls": [],
            }
        self.workflow_calls += 1
        if self.workflow_calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_lane",
                        "name": "lane.create",
                        "args": {
                            "lane_id": "lane_aox_hmm",
                            "name": "aox-hmm-mining",
                            "cwd": "/tmp/openzyme-aox-hmm",
                            "branch_name": "eval/aox-hmm",
                        },
                    },
                    {
                        "id": "call_aox_task",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_aox_hmm_execution",
                            "subject": "Run AOX/HMM mining pipeline",
                            "description": "Create, review, approve, and execute the AOX/HMM mining pipeline from the fixed accession prompt.",
                            "kind": "execution",
                            "priority": "high",
                        },
                    },
                    {
                        "id": "call_aox_bind_task",
                        "name": "lane.bind_task",
                        "args": {
                            "task_id": "task_aox_hmm_execution",
                            "lane_id": "lane_aox_hmm",
                        },
                    },
                ],
            }
        if self.workflow_calls == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_delegate",
                        "name": "task.delegate",
                        "args": {
                            "task_id": "task_aox_hmm_execution",
                            "agent_role": "executor",
                            "instructions": (
                                "Use the execution SDK docs to author an AOX/HMM pipeline from the fixed 13 accessions. "
                                "Create a source artifact, patch it, diff it, run dry-run, then request single-plan approval before execution."
                            ),
                        },
                    }
                ],
            }
        return {"content": "AOX/HMM execution is waiting for the executor workflow.", "tool_calls": []}


class V3AOXHMMEvalModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, V3AOXHMMEvalInvoker] = {}

    def create_structured_invoker(self, *, purpose: str) -> V3LocalEvalStructuredInvoker:
        return V3LocalEvalStructuredInvoker(purpose)

    def create_tool_calling_invoker(self, *, purpose: str) -> V3AOXHMMEvalInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = V3AOXHMMEvalInvoker(purpose)
        return self.invokers[purpose]


class _AoxHmmFixturePreflight:
    ok = True
    message = "fixture sandbox ready"


class AoxHmmFixtureSandboxRunner:
    def preflight(self) -> _AoxHmmFixturePreflight:
        return _AoxHmmFixturePreflight()

    def run_pipeline(
        self,
        *,
        session_id: str,
        invocation_id: str,
        code: str,
        inputs: tuple[SessionArtifactRecord, ...] = (),
        control_handler: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> ExecutionOutcome:
        del session_id, code, inputs
        if control_handler is None:
            raise RuntimeError("AOX/HMM fixture sandbox requires a control handler")
        reference = control_handler(
            "bio.ncbi_fetch_proteins",
            {
                "accessions": list(AOX_HMM_ACCESSIONS),
                "fields": ["definition", "organism", "length"],
                "output_dir": "/workspace/output/bio/ncbi",
            },
        )

        def artifact_id_by_suffix(result: dict[str, Any], suffix: str) -> str:
            for artifact in list(result.get("artifacts") or []):
                if str(artifact.get("relative_path") or "").endswith(suffix):
                    return str(artifact["artifact_id"])
            raise RuntimeError(f"Missing expected artifact suffix: {suffix}")

        reference_fasta_id = artifact_id_by_suffix(reference, "provider_parsed/proteins.fasta")
        workspace = dict(control_handler("hpc.workspace", {"label": "aox_hmm"}))

        def stage(artifact_id: str, path: str) -> dict[str, Any]:
            return dict(
                control_handler(
                    "hpc.stage_artifact",
                    {
                        "hpc_workspace": workspace,
                        "artifact_id": artifact_id,
                        "workspace_path": path,
                    },
                )
            )

        def fetch(run: dict[str, Any]) -> dict[str, Any]:
            return dict(
                control_handler(
                    "hpc.fetch_outputs",
                    {
                        "hpc_workspace": workspace,
                        "run_id": run["run_id"],
                    },
                )
            )

        reference_remote = stage(reference_fasta_id, "inputs/reference.fasta")
        cdhit90 = fetch(
            control_handler(
                "bio_tools.cdhit",
                {
                    "input_fasta": reference_remote,
                    "placement": workspace,
                    "expected_outputs": [
                        {"path": "bio_tools/cdhit/clustered.fasta", "kind": "sequence", "format": "fasta"},
                        {"path": "bio_tools/cdhit/clusters.csv", "kind": "result", "format": "csv"},
                    ],
                    "identity": 0.9,
                    "mode": "reference",
                },
            )
        )
        alignment_remote = stage(cdhit90["registered_artifact_ids"][0], "inputs/alignment_input.fasta")
        alignment = fetch(
            control_handler(
                "bio_tools.mafft",
                {
                    "input_fasta": alignment_remote,
                    "placement": workspace,
                    "expected_outputs": [{"path": "bio_tools/mafft/alignment.fasta", "kind": "sequence"}],
                    "params": {},
                },
            )
        )
        hmm = fetch(
            control_handler(
                "bio_tools.hmmbuild",
                {
                    "alignment": stage(alignment["registered_artifact_ids"][0], "inputs/alignment.fasta"),
                    "placement": workspace,
                    "expected_outputs": [{"path": "bio_tools/hmmbuild/model.hmm", "kind": "result"}],
                    "params": {},
                },
            )
        )
        hmm_remote = stage(hmm["registered_artifact_ids"][0], "inputs/model.hmm")
        fetch(
            control_handler(
                "bio_tools.hmmalign",
                {
                    "hmm": hmm_remote,
                    "fasta": reference_remote,
                    "placement": workspace,
                    "expected_outputs": [{"path": "bio_tools/hmmalign/aligned.fasta", "kind": "sequence"}],
                    "params": {},
                },
            )
        )
        control_handler(
            "bio.hmmer_search",
            {
                "hmm_artifact_id": hmm["registered_artifact_ids"][0],
                "database": "refprot",
                "output_dir": "/workspace/output/bio/hmmer",
                "params": {"evalue": "1e-20", "query": "aox"},
            },
        )
        cdhit85 = fetch(
            control_handler(
                "bio_tools.cdhit",
                {
                    "input_fasta": reference_remote,
                    "placement": workspace,
                    "expected_outputs": [
                        {"path": "bio_tools/cdhit/clustered.fasta", "kind": "sequence", "format": "fasta"},
                        {"path": "bio_tools/cdhit/clusters.csv", "kind": "result", "format": "csv"},
                    ],
                    "identity": 0.85,
                    "mode": "candidate",
                },
            )
        )

        output_dir = Path(tempfile.gettempdir()) / "openzyme-aox-hmm-fixture" / invocation_id
        output_dir.mkdir(parents=True, exist_ok=True)
        candidates = AOX_HMM_ACCESSIONS[:5]

        def fasta_for(accessions: tuple[str, ...]) -> str:
            return "".join(
                f">{accession} candidate\nMSEQUENCE{index}AOX\n"
                for index, accession in enumerate(accessions, start=1)
            )

        def write_artifact(
            relative_path: str,
            content: str,
            *,
            kind: ArtifactKind = ArtifactKind.RESULT,
            metadata: dict[str, Any] | None = None,
        ) -> ExecutionArtifactRef:
            metadata_payload = dict(metadata or {})
            self._validate_output_content(relative_path, content, metadata_payload)
            path = output_dir / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ExecutionArtifactRef(
                storage_uri=str(path),
                relative_path=f"aox_hmm/{relative_path}",
                kind=kind,
                metadata=metadata_payload,
            )

        hits_raw_rows = ["target,uniprot_accession,hmm_score,evalue,length"]
        hits_filtered_rows = ["target,uniprot_accession,hmm_score,evalue,length,sequence"]
        scoring_rows = ["id,seq_score,pass_rule,activity_score,reference_coordinate"]
        nodes = ["node_id,label,score,cluster_id"]
        edges = ["source,target,similarity"]
        for index, accession in enumerate(candidates, start=1):
            hmm_score = 240 - index
            seq_score = 40 - index
            sequence = f"MSEQUENCE{index}AOX"
            hits_raw_rows.append(
                f"target_{index},{accession},{hmm_score},1e-{20 + index},{650 + index}"
            )
            hits_filtered_rows.append(
                f"target_{index},{accession},{hmm_score},1e-{20 + index},{650 + index},{sequence}"
            )
            scoring_rows.append(f"{accession},{seq_score},true,{seq_score},AAB57849.1")
            nodes.append(f"{accession},candidate {index},{seq_score},cluster_1")
        for left, right in zip(candidates, candidates[1:]):
            edges.append(f"{left},{right},0.91")
        artifacts = (
            write_artifact(
                "AOX_ref21.fasta",
                fasta_for(AOX_HMM_ACCESSIONS),
                kind=ArtifactKind.SEQUENCE,
                metadata={
                    "format": "fasta",
                    "accession_count": len(AOX_HMM_ACCESSIONS),
                    "provider_request_ids": list(reference["artifact_ids"]),
                },
            ),
            write_artifact(
                "target.fasta",
                fasta_for(candidates),
                kind=ArtifactKind.SEQUENCE,
                metadata={"format": "fasta", "warning_policy": "empty_target_requires_structured_warning"},
            ),
            write_artifact(
                "AOX_ref.hmm",
                "HMMER3/f [fixture]\nNAME AOX_ref\n//\n",
                metadata={
                    "format": "hmm",
                    "source_reference_fasta_artifact_id": reference_fasta_id,
                    "mafft_artifact_ids": list(alignment["registered_artifact_ids"]),
                    "hmmbuild_artifact_ids": list(hmm["registered_artifact_ids"]),
                },
            ),
            write_artifact(
                "hits_raw.csv",
                "\n".join(hits_raw_rows) + "\n",
                metadata={
                    "format": "csv",
                    "required_columns": ["target", "uniprot_accession", "hmm_score", "evalue", "length"],
                },
            ),
            write_artifact(
                "hits_len650_700_200.csv",
                "\n".join(hits_filtered_rows) + "\n",
                metadata={
                    "format": "csv",
                    "required_columns": [
                        "target",
                        "uniprot_accession",
                        "hmm_score",
                        "evalue",
                        "length",
                        "sequence",
                    ],
                },
            ),
            write_artifact(
                "scored_ref_plus_hits.csv",
                "\n".join(scoring_rows) + "\n",
                metadata={"format": "csv", "required_columns": ["id", "seq_score", "pass_rule"]},
            ),
            write_artifact(
                "AOX_candidates.fasta",
                fasta_for(candidates[:3]),
                kind=ArtifactKind.SEQUENCE,
                metadata={"format": "fasta", "activity_score_threshold": 33.6},
            ),
            write_artifact(
                "AOX_candidates_cdhit85.fasta",
                fasta_for(candidates[:3]),
                kind=ArtifactKind.SEQUENCE,
                metadata={
                    "format": "fasta",
                    "tool_name": "cd-hit",
                    "identity": 0.85,
                    "source_operation_artifact_ids": list(cdhit85["registered_artifact_ids"]),
                },
            ),
            write_artifact(
                "nodes.csv",
                "\n".join(nodes) + "\n",
                metadata={"format": "csv", "required_columns": ["node_id", "label", "score", "cluster_id"]},
            ),
            write_artifact(
                "edges_similarity.csv",
                "\n".join(edges) + "\n",
                metadata={"format": "csv", "required_columns": ["source", "target", "similarity"]},
            ),
            write_artifact(
                "execution_summary.json",
                json.dumps(
                    {
                        "accession_count": len(AOX_HMM_ACCESSIONS),
                        "candidate_count": len(candidates),
                        "length_filter": [650, 700],
                        "hmm_score_threshold": 200,
                        "activity_score_threshold": 33.6,
                        "similarity_threshold": 0.85,
                        "hmmer_database": "refprot",
                        "provider_status": "fixture",
                        "tool_status": "fixture",
                        "warning_count": 0,
                        "reference_artifact_ids": list(reference["artifact_ids"]),
                        "cdhit90_artifact_ids": list(cdhit90["registered_artifact_ids"]),
                        "candidate_cdhit85_artifact_ids": list(cdhit85["registered_artifact_ids"]),
                        "artifact_ids": [],
                        "normalized_final_deliverable_paths": sorted(S15_AOX_HMM_FIXED_DELIVERABLES),
                    },
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                metadata={"format": "json", "candidate_count": len(candidates)},
            ),
        )
        return ExecutionOutcome(
            run_id=f"fixture_{invocation_id}",
            status=RunStatus.SUCCEEDED,
            execution_mode="fixture",
            remote_run_dir=f"fixture://{invocation_id}",
            raw_result={"registered_artifact_count": len(artifacts)},
            artifacts=artifacts,
            exit_code=0,
        )

    def _validate_output_content(self, relative_path: str, content: str, metadata: dict[str, Any]) -> None:
        output_format = str(metadata.get("format") or "").lower()
        required_columns = [str(column) for column in list(metadata.get("required_columns") or [])]
        if not content.strip():
            raise ValueError(f"fixture output is empty: {relative_path}")
        if output_format in {"fasta", "fa", "faa"} and not content.lstrip().startswith(">"):
            raise ValueError(f"fixture FASTA output is invalid: {relative_path}")
        if output_format == "hmm" and not content.startswith("HMMER"):
            raise ValueError(f"fixture HMM output is invalid: {relative_path}")
        if output_format == "csv" or required_columns:
            header = content.splitlines()[0].split(",") if content.splitlines() else []
            missing = [column for column in required_columns if column not in header]
            if missing:
                raise ValueError(f"fixture CSV output {relative_path} is missing required columns: {missing}")


def build_local_eval_runtime() -> RuntimeFoundation:
    settings = get_settings()
    return build_local_eval_foundation(
        settings=replace(
            settings,
            llm=replace(settings.llm, api_key=None),
        ),
    )


def build_live_eval_foundation() -> RuntimeFoundation:
    return build_configured_foundation()


def build_v3_eval_repositories() -> CoreRepositories:
    connection = connect_v3_sqlite(":memory:")
    apply_v3_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def seed_v3_eval_execution_artifact(
    repositories: CoreRepositories, session_id: str
) -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "fpocket" / "1ubq.pdb"
    content_digest = f"sha256:{hashlib.sha256(fixture_path.read_bytes()).hexdigest()}"
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_eval_structure",
            session_id=session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri=str(fixture_path),
            relative_path="fixtures/fpocket/1ubq.pdb",
            title="1ubq.pdb",
            description=None,
            metadata={
                "source": "eval_fixture",
                "format": "pdb",
                "validation_profile": "fpocket_valid",
                "content_digest": content_digest,
            },
            created_at="2026-04-20T12:00:03+00:00",
        )
    )


def _poll_v3_background_workspace(
    client: TestClient,
    *,
    session_id: str,
    is_ready: Callable[[dict[str, Any]], bool],
    timeout_seconds: float = 15.0,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    workspace: dict[str, Any] = {}
    event_text = ""
    runtime_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        workspace_response = client.get(f"/v3/sessions/{session_id}/workspace")
        if workspace_response.status_code != 200:
            runtime_response = client.get("/debug/v3-runtime")
            raise RuntimeError(
                {
                    "step": "get_v3_workspace",
                    "status_code": workspace_response.status_code,
                    "body": workspace_response.text,
                    "workspace": workspace,
                    "runtime_status": runtime_response.json()
                    if runtime_response.status_code == 200
                    else runtime_response.text,
                    "events": event_text[-1000:],
                }
            )
        workspace_response.raise_for_status()
        workspace = workspace_response.json()
        events_response = client.get(f"/v3/sessions/{session_id}/events?replay=1")
        if events_response.status_code != 200:
            runtime_response = client.get("/debug/v3-runtime")
            raise RuntimeError(
                {
                    "step": "get_v3_events",
                    "status_code": events_response.status_code,
                    "body": events_response.text,
                    "workspace": workspace,
                    "runtime_status": runtime_response.json()
                    if runtime_response.status_code == 200
                    else runtime_response.text,
                    "events": event_text[-1000:],
                }
            )
        events_response.raise_for_status()
        event_text = events_response.text
        runtime_response = client.get("/debug/v3-runtime")
        runtime_response.raise_for_status()
        runtime_status = runtime_response.json()

        approvals = workspace.get("pending_approvals") or []
        if approvals:
            resolved = client.post(
                f"/v3/approvals/{approvals[0]['approval_id']}/resolve",
                json={"decision": "approved", "actor_ref": "eval"},
            )
            resolved.raise_for_status()
            time.sleep(0.2)
            continue

        if is_ready(workspace):
            return workspace, event_text, runtime_status
        time.sleep(0.2)
    return workspace, event_text, runtime_status


S15_TASK_TERMINAL_STATUS_VALUES = {"completed", "failed", "cancelled"}
S15_SANDBOX_RUN_TERMINAL_STATUS_VALUES = {
    "completed",
    "failed",
    "timeout",
    "resource_exceeded",
    "cancelled",
}
S15_CONTROLLED_OPERATION_TERMINAL_STATUS_VALUES = {
    "completed",
    "failed",
    "recovery_failed",
}


def _s15_aox_execution_task_status(workspace: dict[str, Any]) -> str | None:
    for item in (workspace.get("task_board") or {}).get("items", []):
        task = item.get("task") if isinstance(item, dict) else None
        if isinstance(task, dict) and task.get("task_id") == "task_aox_hmm_execution":
            status = task.get("status")
            return None if status is None else str(status)
    return None


def _s15_fixture_workspace_ready(workspace: dict[str, Any]) -> bool:
    return (
        not workspace.get("pending_approvals")
        and _s15_aox_execution_task_status(workspace) == "completed"
        and "execution" in workspace["capabilities"]
        and any(
            item.get("status") == "succeeded"
            for item in workspace["capabilities"]["execution"]
        )
        and any(
            message.get("role") == "assistant"
            and "AOX/HMM mining completed" in str(message.get("content") or "")
            for message in workspace["conversation"]
        )
    )


def _s15_live_workspace_ready(
    repositories: CoreRepositories,
    *,
    session_id: str,
    workspace: dict[str, Any],
) -> bool:
    if workspace.get("pending_approvals"):
        return False
    task_status = _s15_aox_execution_task_status(workspace)
    if task_status not in S15_TASK_TERMINAL_STATUS_VALUES:
        return False
    artifact_paths = {
        artifact.relative_path
        for artifact in repositories.artifacts.list_by_session(session_id)
    }
    fixed_outputs_ready = S15_AOX_HMM_FIXED_DELIVERABLES <= artifact_paths
    sandbox_terminal = any(
        run.status.value in S15_SANDBOX_RUN_TERMINAL_STATUS_VALUES
        for run in repositories.sandbox_runs.list_by_session(session_id)
    )
    operations = repositories.controlled_operations.list_by_session(session_id)
    operations_terminal = bool(operations) and all(
        operation.status.value in S15_CONTROLLED_OPERATION_TERMINAL_STATUS_VALUES
        for operation in operations
    )
    final_answer_seen = _s15_final_answer(workspace) is not None
    return bool(
        fixed_outputs_ready
        or sandbox_terminal
        or operations_terminal
        or final_answer_seen
    )


def _run_v3_design_cutover_scenario(
    *,
    foundation_builder: FoundationBuilder,
    model_factory: Any | None,
    upload_results: bool = False,
    scenario_id: str = "v3_design_cutover_path",
) -> dict[str, Any]:
    objective = (
        "Given a literature brief on a thermostable enzyme scaffold, extract design "
        "goals and run the V3 research, execution, and report delivery path."
    )
    with tempfile.TemporaryDirectory(prefix="openzyme-v3-eval-"):
        foundation = foundation_builder()
        if model_factory is not None:
            foundation = replace(foundation, model_factory=model_factory)
        v3_repositories = build_v3_eval_repositories()
        app = create_app(
            HostApiDependencies(
                foundation=foundation,
                v3_repositories=v3_repositories,
                v3_background_runtime_enabled=True,
            )
        )
        with TestClient(app) as client:
            created = client.post(
                "/v3/sessions",
                json={
                    "session_id": "sess_eval_v3_cutover",
                    "project_id": "proj_001",
                    "objective": objective,
                    "title": "V3 cutover eval",
                },
            )
            created.raise_for_status()
            seed_v3_eval_execution_artifact(v3_repositories, "sess_eval_v3_cutover")

            prompt = (
                "Use this literature brief to run the V3 design workflow. "
                "A glycoside hydrolase scaffold retains activity after 65 C heat "
                "challenge but needs improved substrate turnover on soluble xylan. "
                "Extract design goals, delegate research, run an execution check, "
                "and stop for approval if execution requires it."
            )
            with workflow_trace(
                "openzyme.v3_eval_scenario",
                action="v3_local_eval" if model_factory is not None else "v3_live_eval",
                project_id="proj_001",
                phase="evaluation",
                inputs={"scenario_id": scenario_id, "objective": objective},
                enabled=upload_results,
            ) as run:
                first_turn = client.post(
                    "/v3/sessions/sess_eval_v3_cutover/messages",
                    json={"message": prompt},
                )
                first_turn.raise_for_status()
                _poll_v3_background_workspace(
                    client,
                    session_id="sess_eval_v3_cutover",
                    is_ready=lambda workspace: (
                        "deep_research" in workspace["capabilities"]
                        and workspace["capabilities"]["deep_research"][0]["status"]
                        == "succeeded"
                        and "execution" in workspace["capabilities"]
                        and workspace["capabilities"]["execution"][0]["status"]
                        == "succeeded"
                    ),
                )

                report_turn = client.post(
                    "/v3/sessions/sess_eval_v3_cutover/messages",
                    json={
                        "message": "Publish the final report from the completed research and execution evidence.",
                    },
                )
                report_turn.raise_for_status()
                workspace, event_text, runtime_status = _poll_v3_background_workspace(
                    client,
                    session_id="sess_eval_v3_cutover",
                    is_ready=lambda workspace: (
                        bool(workspace["reports"])
                        and bool(workspace["report_drafts"])
                        and workspace["report_drafts"][0]["status"] == "published"
                    ),
                )
                tasks = [item["task"] for item in workspace["task_board"]["items"]]
                task_kinds = {task["kind"] for task in tasks}
                agent_roles = {
                    item["agent"]["role"] for item in workspace["delegation"]["agents"]
                }
                capability_keys = set(workspace["capabilities"])
                report_drafts = workspace["report_drafts"]
                reports = workspace["reports"]
                checks = {
                    "task_create_event": "event: task.created" in event_text,
                    "delegate_tool_event": "task.delegate" in event_text,
                    "teammate_wakeup": bool(
                        agent_roles & {"researcher", "executor", "reporter"}
                    ),
                    "background_runtime": runtime_status.get("worker_id")
                    == "host-api:background-runtime"
                    and int(runtime_status.get("processed_signal_count") or 0) > 0,
                    "signal_lifecycle": "event: signal.claimed" in event_text
                    and "event: signal.completed" in event_text,
                    "research_completed": "deep_research" in capability_keys
                    and workspace["capabilities"]["deep_research"][0]["status"]
                    == "succeeded",
                    "execution_artifact": bool(workspace["artifacts"])
                    and "execution" in capability_keys
                    and workspace["capabilities"]["execution"][0]["status"]
                    == "succeeded",
                    "report_draft_published": bool(report_drafts)
                    and report_drafts[0]["status"] == "published",
                    "final_report_ready": bool(reports)
                    and reports[0]["status"] == "ready",
                    "workspace_projection": {"research", "execution", "reporting"}
                    <= task_kinds,
                }
                result = {
                    "scenario_id": scenario_id,
                    "session_id": workspace["session"]["session_id"],
                    "task_count": len(tasks),
                    "agent_roles": sorted(agent_roles),
                    "capability_keys": sorted(capability_keys),
                    "report_count": len(reports),
                    "checks": checks,
                    "passed": all(checks.values()),
                }
                if run is not None:
                    run.end(outputs=result)
                return result


def _run_v3_aox_hmm_prompt_scenario(
    *,
    foundation_builder: FoundationBuilder,
    model_factory: Any | None,
    upload_results: bool = False,
    scenario_id: str = S15_AOX_HMM_SCENARIO_ID,
    scenario_class: str = "live",
    use_fixture_dependencies: bool = False,
    prerequisite_report: dict[str, object] | None = None,
) -> dict[str, Any]:
    if scenario_class == "live" and use_fixture_dependencies:
        raise ValueError("S15 live AOX/HMM scenario cannot use fixture dependencies")
    objective = (
        "Run AOX/HMM mining from a natural language prompt using V3 task delegation, "
        "persistent sandbox source execution, SDK approval, Host-supervised providers/tools, "
        "artifact catalog registration, and final answer evidence."
    )
    session_id = "sess_eval_aox_hmm"
    with tempfile.TemporaryDirectory(prefix="openzyme-v3-aox-hmm-eval-") as temp_dir:
        foundation = foundation_builder()
        if model_factory is not None:
            foundation = replace(foundation, model_factory=model_factory)
        v3_repositories = build_v3_eval_repositories()
        if scenario_class == "live" and prerequisite_report is not None:
            _s15_bootstrap_live_sandbox_image(v3_repositories, prerequisite_report)
        dependencies_kwargs: dict[str, Any] = {
            "foundation": foundation,
            "v3_repositories": v3_repositories,
            "v3_background_runtime_enabled": True,
        }
        if use_fixture_dependencies:
            dependencies_kwargs.update(
                {
                    "v3_pipeline_sandbox_runner": AoxHmmFixtureSandboxRunner(),
                    "v3_bio_adapter": DeterministicBioDatabaseAdapter(),
                    "v3_allow_bio_fixture_adapter": True,
                }
            )
        app = create_app(HostApiDependencies(**dependencies_kwargs))
        with TestClient(app) as client:
            created = client.post(
                "/v3/sessions",
                json={
                    "session_id": session_id,
                    "project_id": "proj_001",
                    "objective": objective,
                    "title": "AOX/HMM prompt E2E",
                },
            )
            created.raise_for_status()
            prompt = S15_AOX_HMM_FIXED_PROMPT
            with workflow_trace(
                "openzyme.v3_aox_hmm_prompt_eval",
                action="v3_fixture_eval" if scenario_class == "fixture" else "v3_live_eval",
                project_id="proj_001",
                phase="evaluation",
                inputs={"scenario_id": scenario_id, "objective": objective},
                enabled=upload_results,
            ) as run:
                first_turn = client.post(
                    f"/v3/sessions/{session_id}/messages",
                    json={"message": prompt},
                )
                first_turn.raise_for_status()
                poll_timeout_seconds = 45.0 if scenario_class == "fixture" else 900.0
                workspace, event_text, runtime_status = _poll_v3_background_workspace(
                    client,
                    session_id=session_id,
                    timeout_seconds=poll_timeout_seconds,
                    is_ready=(
                        _s15_fixture_workspace_ready
                        if scenario_class == "fixture"
                        else lambda workspace: _s15_live_workspace_ready(
                            v3_repositories,
                            session_id=session_id,
                            workspace=workspace,
                        )
                    ),
                )

                artifacts = v3_repositories.artifacts.list_by_session(session_id)
                artifact_paths = {artifact.relative_path for artifact in artifacts}
                code_artifacts = [
                    artifact
                    for artifact in artifacts
                    if artifact.kind is ArtifactKind.CODE
                    and (artifact.metadata or {}).get("semantic_type") == "pipeline_source"
                ]
                execution_invocations = [
                    invocation
                    for invocation in v3_repositories.invocations.list_by_session(session_id)
                    if invocation.engine_name == "execution"
                ]
                dry_run_invocations = []
                plan_payloads = []
                for invocation in execution_invocations:
                    document = v3_repositories.engine_documents.get(invocation.input_ref)
                    if document is None:
                        continue
                    pipeline = document.payload.get("pipeline")
                    if not isinstance(pipeline, dict):
                        continue
                    if pipeline.get("dry_run"):
                        dry_run_invocations.append(invocation)
                        plan_payloads.append(pipeline.get("execution_plan"))
                terminal_invocations = [
                    invocation
                    for invocation in execution_invocations
                    if invocation.output_ref is not None
                ]
                output_artifacts = [
                    artifact
                    for artifact in artifacts
                    if artifact.invocation_id
                    and artifact.kind is not ArtifactKind.CODE
                    and artifact.relative_path != "logs/stdout.log"
                    and artifact.relative_path != "logs/stderr.log"
                ]
                projected_text = json.dumps(workspace, sort_keys=True)
                artifact_text_by_path: dict[str, str] = {}
                artifact_metadata_by_path: dict[str, dict[str, object]] = {}
                for artifact in artifacts:
                    if artifact.relative_path not in S15_AOX_HMM_FIXED_DELIVERABLES:
                        continue
                    artifact_metadata_by_path[artifact.relative_path] = dict(artifact.metadata or {})
                    try:
                        artifact_text_by_path[artifact.relative_path] = Path(artifact.storage_uri).read_text(
                            encoding="utf-8"
                        )
                    except OSError:
                        artifact_text_by_path[artifact.relative_path] = ""
                final_output_validation = _s15_aox_validate_final_artifacts(
                    artifact_paths,
                    artifact_text_by_path,
                    artifact_metadata_by_path,
                )
                required_paths = _s15_aox_required_artifact_paths()
                plan = next((payload for payload in plan_payloads if isinstance(payload, dict)), {})
                evidence_bundle = _s15_build_evidence_bundle(
                    v3_repositories,
                    scenario_id=scenario_id,
                    session_id=session_id,
                    prompt=prompt,
                    prerequisite_report=prerequisite_report or {"status": "ok", "required": []},
                    workspace=workspace,
                    artifacts=artifacts,
                    required_paths=required_paths,
                    final_output_validation=final_output_validation,
                )
                evidence_bundle_validation = _s15_validate_evidence_bundle(evidence_bundle)
                has_legacy_execution_pipeline = bool(
                    execution_invocations
                ) or _s15_event_text_has_legacy_execution_pipeline(event_text)
                live_product_path_validation = _s15_validate_live_product_path(
                    evidence_bundle,
                    workspace=workspace,
                    has_legacy_execution_pipeline=has_legacy_execution_pipeline,
                )
                checks = {
                    "single_user_prompt": sum(1 for item in workspace["conversation"] if item["role"] == "user") == 1,
                    "delegated_executor": any(
                        item["agent"]["role"] == "executor"
                        for item in workspace["delegation"]["agents"]
                    )
                    and "task.delegate" in event_text,
                    "source_artifact_versions": scenario_class == "live" or {1, 2}.issubset(
                        {
                            int((artifact.metadata or {}).get("version") or 0)
                            for artifact in code_artifacts
                        }
                    ),
                    "source_diff_recorded": scenario_class == "live" or "artifact.diff_text" in event_text,
                    "dry_run_plan": scenario_class == "live" or bool(dry_run_invocations)
                    and bool(plan.get("bio_operations"))
                    and bool(plan.get("bio_tool_operations"))
                    and bool(plan.get("approval_requirements")),
                    "approval_resolved": (
                        "event: approval.requested" in event_text
                        and "event: approval.resolved" in event_text
                    )
                    if scenario_class == "fixture"
                    else bool(evidence_bundle.get("approval_ids"))
                    and not workspace.get("pending_approvals"),
                    "execution_completed": (
                        bool(live_product_path_validation["passed"])
                        if scenario_class == "live"
                        else bool(terminal_invocations)
                    )
                    and any(
                        item.get("status") == "succeeded"
                        for item in workspace["capabilities"].get("execution", [])
                    )
                    if scenario_class == "fixture"
                    else bool(live_product_path_validation["passed"]),
                    "required_artifacts": required_paths <= artifact_paths,
                    "legacy_artifacts_excluded": not _s15_aox_legacy_paths_present(artifact_paths),
                    "candidate85_artifact": any(
                        artifact.relative_path == "aox_hmm/AOX_candidates_cdhit85.fasta"
                        and (artifact.metadata or {}).get("identity") == 0.85
                        for artifact in artifacts
                    ),
                    "final_output_validation": bool(final_output_validation["passed"]),
                    "output_provenance": (
                        bool(output_artifacts)
                        and all(
                            (artifact.metadata or {}).get("source_code_artifact_id")
                            and (artifact.metadata or {}).get("source_code_digest")
                            for artifact in output_artifacts
                        )
                    )
                    if scenario_class == "fixture"
                    else bool(evidence_bundle.get("source_snapshot_digests"))
                    and bool(evidence_bundle.get("registered_artifact_ids")),
                    "safe_projection": "storage_uri" not in projected_text
                    and str(Path(temp_dir)) not in projected_text,
                    "final_answer": (
                        any(
                            message.get("role") == "assistant"
                            and "candidate_count=5" in str(message.get("content") or "")
                            for message in workspace["conversation"]
                        )
                        if scenario_class == "fixture"
                        else bool(evidence_bundle.get("final_answer_available"))
                    ),
                    "background_runtime": runtime_status.get("worker_id") == "host-api:background-runtime"
                    and int(runtime_status.get("processed_signal_count") or 0) > 0,
                    "legacy_pipeline_not_used": scenario_class == "fixture"
                    or not has_legacy_execution_pipeline,
                    "sandbox_product_path": scenario_class == "fixture"
                    or bool(live_product_path_validation["passed"]),
                    "evidence_bundle_complete": bool(evidence_bundle_validation["passed"]),
                }
                live_cutover_check_names = {
                    "required_artifacts",
                    "candidate85_artifact",
                    "final_output_validation",
                    "evidence_bundle_complete",
                    "legacy_pipeline_not_used",
                    "sandbox_product_path",
                }
                passed = (
                    all(checks.values())
                    if scenario_class == "live"
                    else all(
                        value
                        for key, value in checks.items()
                        if key not in live_cutover_check_names
                    )
                )
                safe_summary = {
                    "artifact_count": len(artifacts),
                    "required_artifact_count": len(required_paths),
                    "warning_count": len(evidence_bundle.get("warning_summary") or []),
                    "final_answer_available": evidence_bundle["final_answer_available"],
                    "sandbox_workspace_id": evidence_bundle.get("sandbox_workspace_id"),
                    "status": "passed" if passed else "failed",
                    "evidence_validation": evidence_bundle_validation,
                    "live_product_path_validation": live_product_path_validation,
                }
                live_evidence_refs: dict[str, object] = {
                    "fixed_prompt_digest": f"sha256:{hashlib.sha256(prompt.encode('utf-8')).hexdigest()}",
                    "config_snapshot_digest": None,
                    "prerequisite_report_digest": None,
                    "evidence_bundle_digest": None,
                    "evidence_sealed": False,
                    "safe_summary": safe_summary,
                    "evidence_status": "passed" if passed else "failed",
                }
                if scenario_class == "live":
                    live_evidence_refs = _s15_inline_evidence_refs(
                        scenario_id=scenario_id,
                        session_id=session_id,
                        status="passed" if passed else "failed",
                        prerequisite_report=prerequisite_report or {"status": "ok", "required": []},
                        evidence_payload=evidence_bundle,
                        safe_summary=safe_summary,
                    )
                result = {
                    "scenario_id": scenario_id,
                    "scenario_class": scenario_class,
                    "status": "passed" if passed else "failed",
                    "live_cutover_eligible": scenario_class == "live" and all(checks.values()),
                    **live_evidence_refs,
                    "session_id": session_id,
                    "task_count": len(workspace["task_board"]["items"]),
                    "artifact_count": len(artifacts),
                    "artifact_paths": sorted(artifact_paths),
                    "required_artifact_count": len(required_paths),
                    "required_artifacts": sorted(required_paths),
                    "legacy_artifacts": _s15_aox_legacy_paths_present(artifact_paths),
                    "candidate_count": 5,
                    "final_output_validation": final_output_validation,
                    "evidence_bundle": evidence_bundle,
                    "evidence_bundle_validation": evidence_bundle_validation,
                    "live_product_path_validation": live_product_path_validation,
                    "checks": checks,
                    "passed": passed,
                }
                if run is not None:
                    run.end(outputs=result)
                return result


def run_v3_local_evals(*, upload_results: bool = False) -> dict[str, Any]:
    design_result = _run_v3_design_cutover_scenario(
        foundation_builder=build_local_eval_runtime,
        model_factory=V3LocalEvalModelFactory(),
        upload_results=upload_results,
    )
    aox_result = _run_v3_aox_hmm_prompt_scenario(
        foundation_builder=build_local_eval_runtime,
        model_factory=V3AOXHMMEvalModelFactory(),
        upload_results=upload_results,
        scenario_id=S15_AOX_HMM_FIXTURE_SCENARIO_ID,
        scenario_class="fixture",
        use_fixture_dependencies=True,
    )
    results = [design_result, aox_result]
    passed = sum(1 for result in results if result["passed"])
    return {
        "scenario_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "upload_results": upload_results,
        "results": results,
    }


def _run_v3_live_task_plan_scenario(*, upload_results: bool = False) -> dict[str, Any]:
    objective = (
        "Extract enzyme design goals from a literature abstract and generate an "
        "executable V3 design workflow task plan."
    )
    with tempfile.TemporaryDirectory(prefix="openzyme-v3-live-eval-"):
        foundation = build_live_eval_foundation()
        app = create_app(
            HostApiDependencies(
                foundation=foundation,
                v3_repositories=build_v3_eval_repositories(),
                v3_background_runtime_enabled=True,
            )
        )
        with TestClient(app) as client:
            created = client.post(
                "/v3/sessions",
                json={
                    "session_id": "sess_eval_v3_live_plan",
                    "project_id": "proj_001",
                    "objective": objective,
                    "title": "V3 live task-plan eval",
                },
            )
            created.raise_for_status()
            prompt = (
                "Read this abstract and create an executable design workflow task plan. "
                "Abstract: A thermostable GH10 xylanase variant retains 80% activity "
                "after 65 C incubation, but soluble xylan turnover and alkaline pH "
                "stability remain limiting for biomass pretreatment. "
                "Call task.create exactly three times with these subjects: "
                "'Extract design goals', 'Run execution screen', and "
                "'Draft final report'. Use kind values research, execution, "
                "and reporting respectively. "
                "Then reply with one concise sentence."
            )
            with workflow_trace(
                "openzyme.v3_live_task_plan_eval",
                action="v3_live_eval",
                project_id="proj_001",
                phase="evaluation",
                inputs={
                    "scenario_id": "v3_live_design_task_plan",
                    "objective": objective,
                },
                enabled=upload_results,
            ) as run:
                response = client.post(
                    "/v3/sessions/sess_eval_v3_live_plan/messages",
                    json={"message": prompt},
                )
                response.raise_for_status()
                workspace, event_text, runtime_status = _poll_v3_background_workspace(
                    client,
                    session_id="sess_eval_v3_live_plan",
                    timeout_seconds=240.0,
                    is_ready=lambda current: len(
                        (current.get("task_board") or {}).get("items", [])
                    )
                    >= 3
                    and any(
                        message.get("role") == "assistant"
                        for message in current.get("conversation", [])
                    ),
                )
                tasks = [item["task"] for item in workspace["task_board"]["items"]]
                subjects = {task["subject"] for task in tasks}
                task_kinds = {task["kind"] for task in tasks}
                checks = {
                    "extracted_goal_task": "Extract design goals" in subjects,
                    "execution_task": "Run execution screen" in subjects,
                    "report_task": "Draft final report" in subjects,
                    "full_flow_kinds": {"research", "execution", "reporting"}
                    <= task_kinds,
                    "assistant_output": any(
                        message["role"] == "assistant"
                        for message in workspace["conversation"]
                    ),
                    "background_runtime": runtime_status.get("worker_id")
                    == "host-api:background-runtime",
                    "signal_lifecycle": "event: signal.claimed" in event_text
                    and "event: signal.completed" in event_text,
                    "workspace_projection": len(tasks) >= 3,
                }
                result = {
                    "scenario_id": "v3_live_design_task_plan",
                    "session_id": workspace["session"]["session_id"],
                    "task_count": len(tasks),
                    "subjects": sorted(subjects),
                    "task_kinds": sorted(task_kinds),
                    "checks": checks,
                    "passed": all(checks.values()),
                }
                if run is not None:
                    run.end(outputs=result)
                return result


def _s15_aox_prerequisite_missing_result(
    *,
    upload_results: bool = False,
    prerequisite_report: dict[str, object] | None = None,
) -> dict[str, Any]:
    prerequisite_report = prerequisite_report or _s15_live_prerequisite_report()
    safe_summary = {
        "artifact_count": 0,
        "required_artifact_count": len(S15_AOX_HMM_FIXED_DELIVERABLES),
        "warning_count": len(list(prerequisite_report.get("missing") or [])),
        "final_answer_available": False,
        "sandbox_workspace_id": None,
        "status": "prerequisite_missing",
    }
    live_evidence_refs = _s15_inline_evidence_refs(
        scenario_id=S15_AOX_HMM_SCENARIO_ID,
        session_id=None,
        status="prerequisite_missing",
        prerequisite_report=prerequisite_report,
        evidence_payload=None,
        safe_summary=safe_summary,
    )
    return {
        "scenario_id": S15_AOX_HMM_SCENARIO_ID,
        "scenario_class": "live",
        "status": "prerequisite_missing",
        "passed": False,
        **live_evidence_refs,
        "upload_results": upload_results,
        "required_artifacts": sorted(S15_AOX_HMM_FIXED_DELIVERABLES),
        "prerequisite_report": prerequisite_report,
        "evidence_bundle": None,
        "checks": {
            "live_prerequisites": False,
            "fixture_dependencies_forbidden": True,
            "fixed_prompt": True,
            "fixed_deliverable_contract": True,
            "legacy_artifacts_excluded": True,
        },
    }


def run_v3_live_evals(*, upload_results: bool = False) -> dict[str, Any]:
    result = _run_v3_live_task_plan_scenario(upload_results=upload_results)
    return {
        "scenario_count": 1,
        "passed": 1 if result["passed"] else 0,
        "failed": 0 if result["passed"] else 1,
        "upload_results": upload_results,
        "results": [result],
    }


def run_v3_s15_live_evals(*, upload_results: bool = False) -> dict[str, Any]:
    prerequisite_report = _s15_live_prerequisite_report()
    if prerequisite_report["status"] == "prerequisite_missing":
        result = _s15_aox_prerequisite_missing_result(
            upload_results=upload_results,
            prerequisite_report=prerequisite_report,
        )
    else:
        result = _run_v3_aox_hmm_prompt_scenario(
            foundation_builder=build_live_eval_foundation,
            model_factory=None,
            upload_results=upload_results,
            scenario_id=S15_AOX_HMM_SCENARIO_ID,
            scenario_class="live",
            use_fixture_dependencies=False,
            prerequisite_report=prerequisite_report,
        )
        result["prerequisite_report"] = prerequisite_report
    prerequisite_missing = 1 if result.get("status") == "prerequisite_missing" else 0
    failed = 1 if result.get("status") == "failed" else 0
    return {
        "scenario_count": 1,
        "passed": 1 if result["passed"] else 0,
        "failed": failed,
        "prerequisite_missing": prerequisite_missing,
        "upload_results": upload_results,
        "results": [result],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run OpenZyme V3 workflow evals"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use configured live providers for the selected eval path",
    )
    parser.add_argument(
        "--scenario",
        choices=("default", S15_AOX_HMM_SCENARIO_ID),
        default="default",
        help="Select the live eval scenario; default keeps the generic V3 live smoke.",
    )
    parser.add_argument(
        "--upload-results",
        action="store_true",
        help="Enable LangSmith trace upload for eval scenario runs",
    )
    args = parser.parse_args(argv)
    if not args.live:
        summary = run_v3_local_evals(upload_results=args.upload_results)
    elif args.scenario == S15_AOX_HMM_SCENARIO_ID:
        summary = run_v3_s15_live_evals(upload_results=args.upload_results)
    else:
        summary = run_v3_live_evals(upload_results=args.upload_results)
    print(summary)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
