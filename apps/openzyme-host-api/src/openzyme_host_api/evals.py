from __future__ import annotations

import argparse
import csv
from contextlib import ExitStack
from decimal import Decimal
from decimal import InvalidOperation
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
import tempfile
import time
from typing import Any
from typing import Callable

from fastapi.testclient import TestClient
from openzyme_core import CoreRepositories
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import sandbox_image_record
from openzyme_core import normalize_immutable_image_id
from openzyme_core.sandbox_runtime import S12_ROUTE_POLICIES
from openzyme_core.sandbox_workspace import DEFAULT_SANDBOX_IMAGE_REF
from openzyme_core.workflow_knowledge import default_workflow_registry
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
from openzyme_pipeline import aox_hmmer
from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_reference
from openzyme_pipeline import aox_sequence_join
from openzyme_pipeline import aox_similarity
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
from .security import HostSecurityPolicy
from .tracing import workflow_trace


FoundationBuilder = Callable[[], RuntimeFoundation]


def _eval_security_policy() -> HostSecurityPolicy:
    return HostSecurityPolicy(
        deployment_profile="local-dev",
        principals_by_digest={},
        debug_enabled=True,
    )


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


def _latest_tool_payload(
    messages: list[object], tool_name: str
) -> dict[str, object] | None:
    for message in reversed(messages):
        if _tool_message_name(message) == tool_name:
            return _tool_message_payload(message)
    return None


def _projection_privacy_validation(
    projection: object,
    *,
    forbidden_value: str,
) -> dict[str, object]:
    private_field_paths: list[str] = []
    forbidden_value_paths: list[str] = []

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child_path = f"{path}.{key}"
                if key == "storage_uri":
                    private_field_paths.append(child_path)
                visit(item, child_path)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
            return
        if isinstance(value, str) and forbidden_value and forbidden_value in value:
            forbidden_value_paths.append(path)

    visit(projection, "$")
    return {
        "passed": not private_field_paths and not forbidden_value_paths,
        "private_field_paths": sorted(set(private_field_paths)),
        "forbidden_value_paths": sorted(set(forbidden_value_paths)),
    }


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
                                "topic": "general",
                                "max_results": 3,
                            },
                        }
                    ],
                }
            return {
                "content": "Source-backed enzyme design evidence collected.",
                "tool_calls": [],
            }
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

    def create_structured_invoker(
        self, *, purpose: str
    ) -> "V3LocalEvalStructuredInvoker":
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


AOX_HMM_ACCESSIONS = aox_reference.HMM_REFERENCE_ACCESSIONS
AOX_NCBI_ACCESSIONS = aox_reference.NCBI_REFERENCE_ACCESSIONS

S15_AOX_HMM_SCENARIO_ID = "v3_aox_hmm_cutover_live_e2e"
S15_AOX_HMM_FIXTURE_SCENARIO_ID = "v3_aox_hmm_prompt_fixture"
S15_AOX_HMM_FIXED_PROMPT = (
    "Run AOX/HMM mining from only this one user message. As master, create and "
    "delegate separate research, execution, and reporting tasks to researcher, "
    "executor, and reporter teammates. The researcher must obtain required PubMed "
    "evidence with a real PMID (Semantic Scholar and Tavily are enrichment only). "
    "The reporter must publish a final report whose claims link to the research and "
    "execution artifacts; every teammate must finish its task explicitly. In one "
    "bio.ncbi_fetch_proteins call request these exact 14 identities: "
    + ", ".join(AOX_NCBI_ACCESSIONS)
    + ". Apply aox_hmm_reference_set_selection@1 to materialize AOX_ref21.fasta "
    "with exactly the fixed 13 HMM references, and apply aox_reference_selection@1 "
    "to materialize AOX_coordinate_reference_AAB57849.1.fasta with only AAB57849.1; "
    "both selections must bind the same sealed NCBI input and no identity may be "
    "replaced. Feed only AOX_ref21.fasta to MAFFT, then build AOX_ref.hmm from that "
    "alignment. Search EBI HMMER refprot with bio.hmmer_search, "
    "materialize its provider_parsed/parsed_hits.csv artifact and run the versioned "
    "hmmer_score_filtered_accessions@1 calculation. Register the canonical "
    "aox_hmm/hmmer_score_filtered_accessions.csv before any UniProt call and bind that "
    "exact artifact plus its exact nonempty accessions as bio.uniprot_fetch "
    "source_hit_artifact. If it is empty, do not call UniProt and preserve the typed "
    "upstream-empty reason. After a real UniProt response, join by accession and filter "
    "the fetched sequences to length 650-700; never source length or sequence from the "
    "HMMER response. Apply aox_scoring_input_assembly@1 to materialize "
    "AOX_scoring_input.fasta as AAB57849.1 first followed by the post-UniProt target "
    "records in lexical accession order, then feed AOX_ref.hmm plus that exact scoring "
    "input to HMMalign. Score with "
    "aox_motif_rule_score@1 against reference coordinate AAB57849.1 using the exact "
    "integer-tenths threshold 336 (display 33.6), deduplicate at similarity threshold 0.85, "
    "and export normalized deliverables under aox_hmm/: AOX_ref21.fasta, "
    "AOX_coordinate_reference_AAB57849.1.fasta, AOX_scoring_input.fasta, target.fasta, "
    "AOX_ref.hmm, hits_raw.csv, hmmer_score_filtered_accessions.csv, "
    "hits_len650_700_200.csv, AOX_scoring_alignment.fasta, "
    "scored_ref_plus_hits.csv, AOX_candidates.fasta, AOX_candidates_cdhit85.fasta, "
    "AOX_candidates_cdhit85.clusters.csv, nodes.csv, "
    "edges_similarity.csv, similarity_graph_manifest.json, and execution_summary.json. "
    "A schema-valid empty candidate result is honest success only when its reason and "
    "the independent provider/HPC health evidence are preserved; never synthesize a hit."
)
S15_AOX_HMM_WORKFLOW_REF = next(
    manifest.selection_ref
    for manifest in default_workflow_registry().list_manifests()
    if manifest.workflow_id == "aox-hmm-live"
)
S15_AOX_HMM_FIXED_DELIVERABLES = {
    "aox_hmm/AOX_ref21.fasta",
    "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
    "aox_hmm/AOX_scoring_input.fasta",
    "aox_hmm/target.fasta",
    "aox_hmm/AOX_ref.hmm",
    "aox_hmm/hits_raw.csv",
    "aox_hmm/hmmer_score_filtered_accessions.csv",
    "aox_hmm/hits_len650_700_200.csv",
    "aox_hmm/AOX_scoring_alignment.fasta",
    "aox_hmm/scored_ref_plus_hits.csv",
    "aox_hmm/AOX_candidates.fasta",
    "aox_hmm/AOX_candidates_cdhit85.fasta",
    "aox_hmm/AOX_candidates_cdhit85.clusters.csv",
    "aox_hmm/nodes.csv",
    "aox_hmm/edges_similarity.csv",
    "aox_hmm/similarity_graph_manifest.json",
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
    "aox_hmm/hits_raw.csv": {
        "target",
        "accession",
        "evalue",
        "score",
        "page",
        "hit_index",
        "evalue_numeric",
        "score_numeric",
        "raw_page_digest",
        "raw_hit_digest",
        "parsed_row_digest",
    },
    "aox_hmm/hmmer_score_filtered_accessions.csv": {
        "accession",
        "target",
        "evalue_numeric",
        "score_numeric",
        "raw_page_digest",
        "raw_hit_digest",
        "parsed_row_digest",
    },
    "aox_hmm/hits_len650_700_200.csv": {
        "target",
        "uniprot_accession",
        "hmm_score",
        "evalue",
        "length",
        "sequence",
    },
    "aox_hmm/scored_ref_plus_hits.csv": set(aox_motif.CANONICAL_COLUMNS),
    "aox_hmm/AOX_candidates_cdhit85.clusters.csv": {
        "cluster_id",
        "member_id",
        "representative_id",
        "is_representative",
        "identity_to_representative",
        "member_length",
    },
    "aox_hmm/nodes.csv": set(aox_similarity.NODE_COLUMNS),
    "aox_hmm/edges_similarity.csv": set(aox_similarity.EDGE_COLUMNS),
}
S15_AOX_HMM_REQUIRED_SUMMARY_FIELDS = {
    "accession_count",
    "ncbi_reference_accession_count",
    "filtered_hit_count",
    "scoring_row_count",
    "candidate_count",
    "representative_count",
    "graph_node_count",
    "graph_edge_count",
    "length_filter",
    "hmm_score_threshold",
    "motif_rule_score_threshold_tenths",
    "motif_rule_score_threshold",
    "similarity_threshold",
    "hmmer_database",
    "hmmer_score_filter_contract_id",
    "hmmer_score_filter_contract_digest",
    "hmmer_score_filter_implementation_digest",
    "hmmer_score_filter_input_digest",
    "hmmer_score_filter_output_digest",
    "sequence_length_join_contract_id",
    "sequence_length_join_contract_digest",
    "sequence_length_join_implementation_digest",
    "sequence_length_join_hits_digest",
    "sequence_length_join_target_digest",
    "hmm_reference_set_selection_contract_id",
    "hmm_reference_set_selection_contract_digest",
    "hmm_reference_set_selection_implementation_digest",
    "hmm_reference_set_input_digest",
    "hmm_reference_set_output_digest",
    "scoring_reference_selection_contract_id",
    "scoring_reference_selection_contract_digest",
    "scoring_reference_selection_implementation_digest",
    "scoring_reference_selection_input_digest",
    "scoring_reference_output_digest",
    "scoring_input_assembly_contract_id",
    "scoring_input_assembly_contract_digest",
    "scoring_input_assembly_implementation_digest",
    "scoring_reference_input_digest",
    "post_uniprot_target_input_digest",
    "scoring_contract_id",
    "scoring_contract_digest",
    "scoring_implementation_digest",
    "scoring_reference_accession",
    "scoring_input_digest",
    "scoring_alignment_input_digest",
    "scoring_alignment_digest",
    "cdhit_membership_schema_id",
    "similarity_calculation_id",
    "similarity_calculation_digest",
    "similarity_implementation_digest",
    "similarity_threshold_ppm",
    "candidate_graph_manifest_schema_id",
    "candidate_graph_node_schema_id",
    "candidate_graph_edge_schema_id",
    "candidate_graph_manifest_digest",
    "scientific_outcome",
    "scientific_branch",
    "omitted_operation_roles",
    "upstream_empty_skip_receipt_digest",
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


S15_AOX_HMM_LEGACY_SCIENTIFIC_FIELDS = frozenset(
    {"activity_score", "seq_score", "pass_rule"}
)
S15_AOX_HMM_CDHIT_MEMBERSHIP_COLUMNS = (
    "cluster_id",
    "member_id",
    "representative_id",
    "is_representative",
    "identity_to_representative",
    "member_length",
)
_S15_AOX_SEQUENCE_PATTERN = re.compile(r"^[A-Z]+$")
_S15_AOX_CDHIT_IDENTITY_PATTERN = re.compile(r"(?:0|1)\.[0-9]{6}")
_S15_AOX_SYNTHETIC_MARKERS = ("MSEQUENCE", "FIXTURE", "SYNTHETIC")


def _s15_aox_content_digest(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _s15_aox_reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _s15_aox_error(
    errors: list[dict[str, object]],
    error_code: str,
    *,
    path: str | None = None,
    **details: object,
) -> None:
    error: dict[str, object] = {"error_code": error_code}
    if path is not None:
        error["path"] = path
    error.update(details)
    errors.append(error)


def _s15_aox_parse_fasta(
    text: str,
    *,
    path: str,
    errors: list[dict[str, object]],
    allow_empty: bool,
) -> dict[str, str] | None:
    if not text.strip():
        if allow_empty:
            return {}
        _s15_aox_error(errors, "invalid_fasta", path=path, reason="empty")
        return None
    records: dict[str, str] = {}
    header: str | None = None
    fragments: list[str] = []

    def finish_record() -> bool:
        nonlocal header, fragments
        if header is None:
            return True
        sequence_id = header.split(maxsplit=1)[0] if header else ""
        sequence = "".join(fragments).upper()
        if not sequence_id or not sequence:
            _s15_aox_error(
                errors,
                "invalid_fasta",
                path=path,
                reason="empty_header_or_sequence",
            )
            return False
        if sequence_id in records:
            _s15_aox_error(
                errors,
                "invalid_fasta",
                path=path,
                reason="duplicate_sequence_id",
                sequence_id=sequence_id,
            )
            return False
        if _S15_AOX_SEQUENCE_PATTERN.fullmatch(sequence) is None:
            _s15_aox_error(
                errors,
                "invalid_fasta",
                path=path,
                reason="invalid_sequence_residue",
                sequence_id=sequence_id,
            )
            return False
        upper_header = header.upper()
        if any(
            marker in upper_header or marker in sequence
            for marker in _S15_AOX_SYNTHETIC_MARKERS
        ):
            _s15_aox_error(
                errors,
                "synthetic_sequence_evidence_forbidden",
                path=path,
                sequence_id=sequence_id,
            )
            return False
        records[sequence_id] = sequence
        header = None
        fragments = []
        return True

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if not finish_record():
                return None
            header = line[1:].strip()
            continue
        if header is None or any(character.isspace() for character in line):
            _s15_aox_error(
                errors,
                "invalid_fasta",
                path=path,
                reason="sequence_before_header_or_internal_whitespace",
                line=line_number,
            )
            return None
        fragments.append(line)
    if not finish_record():
        return None
    if not records:
        _s15_aox_error(errors, "invalid_fasta", path=path, reason="no_records")
        return None
    sequences = list(records.values())
    if any(len(set(sequence)) == 1 for sequence in sequences) or (
        path == "aox_hmm/AOX_ref21.fasta"
        and len(sequences) > 1
        and len(set(sequences)) == 1
    ):
        _s15_aox_error(
            errors,
            "constant_sequence_evidence_forbidden",
            path=path,
        )
        return None
    return records


def _s15_aox_parse_csv(
    text: str,
    *,
    path: str,
    expected_columns: tuple[str, ...],
    errors: list[dict[str, object]],
) -> list[dict[str, str]] | None:
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        fieldnames = tuple(reader.fieldnames or ())
        rows = list(reader)
    except csv.Error as exc:
        _s15_aox_error(
            errors,
            "invalid_csv",
            path=path,
            reason=type(exc).__name__,
        )
        return None
    legacy_fields = sorted(
        S15_AOX_HMM_LEGACY_SCIENTIFIC_FIELDS.intersection(fieldnames)
    )
    if legacy_fields:
        _s15_aox_error(
            errors,
            "legacy_scoring_schema_forbidden",
            path=path,
            fields=legacy_fields,
        )
    if fieldnames != expected_columns:
        _s15_aox_error(
            errors,
            "invalid_csv_columns",
            path=path,
            expected_columns=list(expected_columns),
            actual_columns=list(fieldnames),
        )
        return None
    for row_number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            _s15_aox_error(
                errors,
                "invalid_csv_row_shape",
                path=path,
                row=row_number,
            )
            return None
    return [{key: str(value) for key, value in row.items()} for row in rows]


def _s15_aox_fixture_or_legacy_evidence_errors(
    payload: object,
    *,
    path: str,
    errors: list[dict[str, object]],
) -> None:
    fixture_found = False
    legacy_fields: set[str] = set()

    def inspect(value: object) -> None:
        nonlocal fixture_found
        if isinstance(value, dict):
            for raw_key, nested in value.items():
                key = str(raw_key)
                if key in S15_AOX_HMM_LEGACY_SCIENTIFIC_FIELDS:
                    legacy_fields.add(key)
                if key == "fixture" and nested is True:
                    fixture_found = True
                if key == "cutover_eligible" and nested is False:
                    fixture_found = True
                inspect(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                inspect(nested)
        elif isinstance(value, str) and "fixture_non_cutover" in value.casefold():
            fixture_found = True

    inspect(payload)
    if legacy_fields:
        _s15_aox_error(
            errors,
            "legacy_scientific_field_forbidden",
            path=path,
            fields=sorted(legacy_fields),
        )
    if fixture_found:
        _s15_aox_error(errors, "fixture_non_cutover_forbidden", path=path)


def _s15_aox_require_metadata(
    metadata_by_path: dict[str, dict[str, object]],
    *,
    path: str,
    fields: tuple[str, ...],
    errors: list[dict[str, object]],
    error_code: str,
) -> None:
    metadata = metadata_by_path.get(path, {})
    for field in fields:
        if metadata.get(field) in (None, "", [], {}):
            _s15_aox_error(
                errors,
                error_code,
                path=path,
                missing_metadata=field,
            )


def _s15_aox_validate_metadata_values(
    metadata_by_path: dict[str, dict[str, object]],
    *,
    path: str,
    expected: dict[str, object],
    errors: list[dict[str, object]],
    error_code: str,
) -> None:
    metadata = metadata_by_path.get(path, {})
    for field, expected_value in expected.items():
        if metadata.get(field) != expected_value:
            _s15_aox_error(
                errors,
                error_code,
                path=path,
                field=field,
                expected=expected_value,
                actual=metadata.get(field),
            )


def _s15_aox_validate_cdhit_membership(
    rows: list[dict[str, str]] | None,
    *,
    candidates: dict[str, str],
    representatives: dict[str, str] | None,
    errors: list[dict[str, object]],
) -> tuple[set[str], dict[str, str]]:
    path = "aox_hmm/AOX_candidates_cdhit85.clusters.csv"
    if rows is None:
        return set(), {}
    if not candidates:
        if rows:
            _s15_aox_error(
                errors,
                "empty_candidate_membership_not_empty",
                path=path,
                row_count=len(rows),
            )
        if representatives:
            _s15_aox_error(
                errors,
                "empty_candidate_representatives_not_empty",
                path="aox_hmm/AOX_candidates_cdhit85.fasta",
            )
        return set(), {}
    if not rows:
        _s15_aox_error(errors, "cdhit_membership_empty", path=path)
        return set(), {}

    members: dict[str, dict[str, str]] = {}
    clusters: dict[str, list[dict[str, str]]] = {}
    for row_number, row in enumerate(rows, start=2):
        empty_fields = [key for key, value in row.items() if not value.strip()]
        if empty_fields:
            _s15_aox_error(
                errors,
                "cdhit_membership_value_missing",
                path=path,
                row=row_number,
                fields=empty_fields,
            )
            continue
        member_id = row["member_id"]
        if member_id in members:
            _s15_aox_error(
                errors,
                "cdhit_membership_duplicate_member",
                path=path,
                member_id=member_id,
            )
            continue
        if row["is_representative"] not in {"true", "false"}:
            _s15_aox_error(
                errors,
                "cdhit_membership_invalid_representative_flag",
                path=path,
                row=row_number,
            )
        identity_text = row["identity_to_representative"]
        if _S15_AOX_CDHIT_IDENTITY_PATTERN.fullmatch(identity_text) is None:
            _s15_aox_error(
                errors,
                "cdhit_membership_invalid_identity",
                path=path,
                row=row_number,
                value=identity_text,
            )
        else:
            try:
                identity = Decimal(identity_text)
            except InvalidOperation:
                identity = Decimal(-1)
            if not identity.is_finite() or identity < 0 or identity > 1:
                _s15_aox_error(
                    errors,
                    "cdhit_membership_invalid_identity",
                    path=path,
                    row=row_number,
                    value=identity_text,
                )
        try:
            member_length = int(row["member_length"])
        except ValueError:
            member_length = -1
        expected_sequence = candidates.get(member_id)
        if expected_sequence is not None and member_length != len(expected_sequence):
            _s15_aox_error(
                errors,
                "cdhit_membership_length_mismatch",
                path=path,
                member_id=member_id,
                expected=len(expected_sequence),
                actual=member_length,
            )
        members[member_id] = row
        clusters.setdefault(row["cluster_id"], []).append(row)

    missing_members = sorted(set(candidates) - set(members))
    unexpected_members = sorted(set(members) - set(candidates))
    if missing_members or unexpected_members:
        _s15_aox_error(
            errors,
            "cdhit_membership_candidate_mismatch",
            path=path,
            missing_member_ids=missing_members,
            unexpected_member_ids=unexpected_members,
        )

    representative_ids: set[str] = set()
    member_clusters: dict[str, str] = {}
    for cluster_id, cluster_rows in clusters.items():
        representative_rows = [
            row for row in cluster_rows if row["is_representative"] == "true"
        ]
        if len(representative_rows) != 1:
            _s15_aox_error(
                errors,
                "cdhit_membership_representative_count_invalid",
                path=path,
                cluster_id=cluster_id,
                representative_count=len(representative_rows),
            )
            continue
        representative = representative_rows[0]
        representative_id = representative["member_id"]
        representative_ids.add(representative_id)
        if (
            representative["representative_id"] != representative_id
            or representative["identity_to_representative"] != "1.000000"
            or any(
                row["representative_id"] != representative_id for row in cluster_rows
            )
        ):
            _s15_aox_error(
                errors,
                "cdhit_membership_representative_inconsistent",
                path=path,
                cluster_id=cluster_id,
            )
        for row in cluster_rows:
            member_clusters[row["member_id"]] = cluster_id

    actual_representatives = set(representatives or {})
    if actual_representatives != representative_ids:
        _s15_aox_error(
            errors,
            "cdhit_representative_fasta_mismatch",
            path="aox_hmm/AOX_candidates_cdhit85.fasta",
            missing_representative_ids=sorted(
                representative_ids - actual_representatives
            ),
            unexpected_representative_ids=sorted(
                actual_representatives - representative_ids
            ),
        )
    for representative_id in sorted(representative_ids & actual_representatives):
        if representatives is not None and representatives[
            representative_id
        ] != candidates.get(representative_id):
            _s15_aox_error(
                errors,
                "cdhit_representative_sequence_mismatch",
                path="aox_hmm/AOX_candidates_cdhit85.fasta",
                representative_id=representative_id,
            )
    return representative_ids, member_clusters


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
            loaded_summary = json.loads(
                summary_text,
                object_pairs_hook=_s15_aox_reject_duplicate_json_keys,
            )
        except (json.JSONDecodeError, ValueError):
            _s15_aox_error(
                errors,
                "invalid_json",
                path="aox_hmm/execution_summary.json",
            )
        else:
            if isinstance(loaded_summary, dict):
                execution_summary = loaded_summary
            else:
                _s15_aox_error(
                    errors,
                    "invalid_json",
                    path="aox_hmm/execution_summary.json",
                )

    _s15_aox_fixture_or_legacy_evidence_errors(
        execution_summary,
        path="aox_hmm/execution_summary.json",
        errors=errors,
    )
    for path, metadata in sorted(metadata_by_path.items()):
        if path in S15_AOX_HMM_FIXED_DELIVERABLES:
            _s15_aox_fixture_or_legacy_evidence_errors(
                metadata,
                path=path,
                errors=errors,
            )

    reference_path = "aox_hmm/AOX_ref21.fasta"
    reference_text = artifact_text_by_path.get(reference_path, "")
    reference_records: dict[str, str] | None = None
    reference_digest = _s15_aox_content_digest(reference_text)
    if reference_path in artifact_paths:
        reference_records = _s15_aox_parse_fasta(
            reference_text,
            path=reference_path,
            errors=errors,
            allow_empty=False,
        )
        metadata = metadata_by_path.get(reference_path, {})
        if metadata.get("accession_count") != len(AOX_HMM_ACCESSIONS):
            _s15_aox_error(
                errors,
                "invalid_accession_count",
                path=reference_path,
                accession_count=metadata.get("accession_count"),
            )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=reference_path,
            fields=("source_ncbi_fasta_artifact_id", "provider_request_ids"),
            errors=errors,
            error_code="provider_provenance_incomplete",
        )
        _s15_aox_validate_metadata_values(
            metadata_by_path,
            path=reference_path,
            expected={
                "contract_id": (
                    aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
                ),
                "contract_digest": (
                    aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
                ),
                "implementation_digest": (
                    aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
                ),
                "output_digest": reference_digest,
                "output_name": aox_reference.HMM_REFERENCE_SET_OUTPUT_NAME,
                "selected_accessions": list(AOX_HMM_ACCESSIONS),
                "excluded_accessions": [
                    aox_reference.SCORING_REFERENCE_ACCESSION
                ],
                "identity_replacement_count": 0,
                "ncbi_reference_accessions": list(AOX_NCBI_ACCESSIONS),
            },
            errors=errors,
            error_code="hmm_reference_selection_metadata_mismatch",
        )
        if reference_records is not None:
            actual_ids = tuple(reference_records)
            if actual_ids != AOX_HMM_ACCESSIONS:
                _s15_aox_error(
                    errors,
                    "hmm_reference_identity_order_mismatch",
                    path=reference_path,
                    expected=list(AOX_HMM_ACCESSIONS),
                    actual=list(actual_ids),
                )
            canonical_reference_text = "".join(
                f">{accession}\n{reference_records[accession]}\n"
                for accession in reference_records
            )
            if reference_text != canonical_reference_text:
                _s15_aox_error(
                    errors,
                    "hmm_reference_fasta_not_canonical",
                    path=reference_path,
                )

    scoring_reference_path = (
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta"
    )
    scoring_reference_text = artifact_text_by_path.get(
        scoring_reference_path,
        "",
    )
    scoring_reference_records: dict[str, str] | None = None
    scoring_reference_digest = _s15_aox_content_digest(scoring_reference_text)
    if scoring_reference_path in artifact_paths:
        scoring_reference_records = _s15_aox_parse_fasta(
            scoring_reference_text,
            path=scoring_reference_path,
            errors=errors,
            allow_empty=False,
        )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=scoring_reference_path,
            fields=("source_ncbi_fasta_artifact_id", "provider_request_ids"),
            errors=errors,
            error_code="provider_provenance_incomplete",
        )
        _s15_aox_validate_metadata_values(
            metadata_by_path,
            path=scoring_reference_path,
            expected={
                "contract_id": (
                    aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
                ),
                "contract_digest": (
                    aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
                ),
                "implementation_digest": (
                    aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
                ),
                "output_digest": scoring_reference_digest,
                "output_name": aox_reference.SCORING_REFERENCE_OUTPUT_NAME,
                "reference_accession": (
                    aox_reference.SCORING_REFERENCE_ACCESSION
                ),
                "identity_replacement_count": 0,
                "ncbi_reference_accessions": list(AOX_NCBI_ACCESSIONS),
            },
            errors=errors,
            error_code="scoring_reference_selection_metadata_mismatch",
        )
        if scoring_reference_records is not None:
            expected_reference_ids = (
                aox_reference.SCORING_REFERENCE_ACCESSION,
            )
            actual_ids = tuple(scoring_reference_records)
            if actual_ids != expected_reference_ids:
                _s15_aox_error(
                    errors,
                    "scoring_reference_identity_mismatch",
                    path=scoring_reference_path,
                    expected=list(expected_reference_ids),
                    actual=list(actual_ids),
                )
            canonical_scoring_reference_text = "".join(
                f">{accession}\n{scoring_reference_records[accession]}\n"
                for accession in scoring_reference_records
            )
            if scoring_reference_text != canonical_scoring_reference_text:
                _s15_aox_error(
                    errors,
                    "scoring_reference_fasta_not_canonical",
                    path=scoring_reference_path,
                )

    if reference_path in artifact_paths and scoring_reference_path in artifact_paths:
        reference_metadata = metadata_by_path.get(reference_path, {})
        scoring_reference_metadata = metadata_by_path.get(
            scoring_reference_path,
            {},
        )
        for field in (
            "input_digest",
            "source_ncbi_fasta_artifact_id",
            "provider_request_ids",
            "ncbi_reference_accessions",
        ):
            if reference_metadata.get(field) != scoring_reference_metadata.get(field):
                _s15_aox_error(
                    errors,
                    "reference_selection_source_mismatch",
                    path=scoring_reference_path,
                    field=field,
                    hmm_reference_value=reference_metadata.get(field),
                    scoring_reference_value=scoring_reference_metadata.get(field),
                )

    target_path = "aox_hmm/target.fasta"
    target_text = artifact_text_by_path.get(target_path, "")
    target_records: dict[str, str] | None = None
    if target_path in artifact_paths:
        target_records = _s15_aox_parse_fasta(
            target_text,
            path=target_path,
            errors=errors,
            allow_empty=True,
        )
        if not target_text.strip():
            warning_count = execution_summary.get("warning_count")
            if (
                isinstance(warning_count, bool)
                or not isinstance(warning_count, int)
                or warning_count <= 0
            ):
                _s15_aox_error(
                    errors,
                    "empty_target_warning_missing",
                    path=target_path,
                )

    scoring_input_path = "aox_hmm/AOX_scoring_input.fasta"
    scoring_input_text = artifact_text_by_path.get(scoring_input_path, "")
    scoring_input_result: aox_reference.ScoringInputAssemblyResult | None = None
    if scoring_input_path in artifact_paths:
        try:
            scoring_input_result = aox_reference.assemble_scoring_input(
                scoring_reference_text,
                target_text,
                expected_contract_id=(
                    aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
                ),
                expected_contract_digest=(
                    aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
                ),
                expected_implementation_digest=(
                    aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
                ),
            )
        except aox_reference.ScientificPrerequisiteError as exc:
            _s15_aox_error(
                errors,
                "scoring_input_assembly_recalculation_failed",
                path=scoring_input_path,
                scientific_error=exc.to_dict(),
            )
        else:
            if scoring_input_text != scoring_input_result.to_fasta():
                _s15_aox_error(
                    errors,
                    "scoring_input_assembly_mismatch",
                    path=scoring_input_path,
                )
            expected_scoring_input_metadata = scoring_input_result.metadata()
            _s15_aox_validate_metadata_values(
                metadata_by_path,
                path=scoring_input_path,
                expected={
                    "contract_id": expected_scoring_input_metadata["contract_id"],
                    "contract_digest": expected_scoring_input_metadata[
                        "contract_digest"
                    ],
                    "implementation_digest": expected_scoring_input_metadata[
                        "implementation_digest"
                    ],
                    "input_digests": expected_scoring_input_metadata[
                        "input_digests"
                    ],
                    "output_digest": expected_scoring_input_metadata["output_digest"],
                    "output_name": expected_scoring_input_metadata["output_name"],
                    "reference_accession": expected_scoring_input_metadata[
                        "reference_accession"
                    ],
                    "target_accessions": expected_scoring_input_metadata[
                        "target_accessions"
                    ],
                    "ordering": expected_scoring_input_metadata["ordering"],
                    "healthy_empty": expected_scoring_input_metadata["healthy_empty"],
                },
                errors=errors,
                error_code="scoring_input_assembly_metadata_mismatch",
            )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=scoring_input_path,
            fields=(
                "source_scoring_reference_artifact_id",
                "source_target_fasta_artifact_id",
            ),
            errors=errors,
            error_code="scoring_input_assembly_provenance_incomplete",
        )

    hmm_path = "aox_hmm/AOX_ref.hmm"
    hmm_text = artifact_text_by_path.get(hmm_path, "")
    hmm_digest = _s15_aox_content_digest(hmm_text)
    if hmm_path in artifact_paths:
        if not hmm_text.startswith("HMMER3"):
            _s15_aox_error(errors, "invalid_hmm", path=hmm_path)
        metadata = metadata_by_path.get(hmm_path, {})
        for key in (
            "source_reference_fasta_artifact_id",
            "source_reference_fasta_digest",
            "mafft_artifact_ids",
            "hmmbuild_artifact_ids",
        ):
            if metadata.get(key) in (None, "", [], {}):
                _s15_aox_error(
                    errors,
                    "hmm_provenance_incomplete",
                    path=hmm_path,
                    missing_metadata=key,
                )
        if metadata.get("source_reference_fasta_digest") != reference_digest:
            _s15_aox_error(
                errors,
                "hmm_reference_digest_mismatch",
                path=hmm_path,
                expected=reference_digest,
                actual=metadata.get("source_reference_fasta_digest"),
            )

    hit_csv_specs = {
        "aox_hmm/hits_raw.csv": (
            "target",
            "accession",
            "evalue",
            "score",
            "page",
            "hit_index",
            "evalue_numeric",
            "score_numeric",
            "raw_page_digest",
            "raw_hit_digest",
            "parsed_row_digest",
        ),
        "aox_hmm/hmmer_score_filtered_accessions.csv": (
            "accession",
            "target",
            "evalue_numeric",
            "score_numeric",
            "raw_page_digest",
            "raw_hit_digest",
            "parsed_row_digest",
        ),
        "aox_hmm/hits_len650_700_200.csv": (
            "target",
            "uniprot_accession",
            "hmm_score",
            "evalue",
            "length",
            "sequence",
        ),
    }
    parsed_csv: dict[str, list[dict[str, str]] | None] = {}
    for path, columns in hit_csv_specs.items():
        if path in artifact_paths:
            parsed_csv[path] = _s15_aox_parse_csv(
                artifact_text_by_path.get(path, ""),
                path=path,
                expected_columns=columns,
                errors=errors,
            )

    raw_hits_path = "aox_hmm/hits_raw.csv"
    score_filtered_path = "aox_hmm/hmmer_score_filtered_accessions.csv"
    score_filter_result: aox_hmmer.ScoreFilteredAccessionsResult | None = None
    if raw_hits_path in artifact_paths and score_filtered_path in artifact_paths:
        try:
            score_filter_result = aox_hmmer.parse_and_filter_csv(
                artifact_text_by_path.get(raw_hits_path, ""),
                expected_contract_id=aox_hmmer.CONTRACT_ID,
                expected_contract_digest=aox_hmmer.CONTRACT_DIGEST,
                expected_implementation_digest=aox_hmmer.IMPLEMENTATION_DIGEST,
            )
            expected_score_filtered = score_filter_result.to_csv()
        except ValueError as exc:
            _s15_aox_error(
                errors,
                "hmmer_score_filter_input_invalid",
                path=raw_hits_path,
                detail=type(exc).__name__,
            )
        else:
            if artifact_text_by_path.get(score_filtered_path, "") != (
                expected_score_filtered
            ):
                _s15_aox_error(
                    errors,
                    "hmmer_score_filter_output_mismatch",
                    path=score_filtered_path,
                )
            _s15_aox_validate_metadata_values(
                metadata_by_path,
                path=score_filtered_path,
                expected=score_filter_result.metadata(),
                errors=errors,
                error_code="hmmer_score_filter_metadata_mismatch",
            )
            _s15_aox_require_metadata(
                metadata_by_path,
                path=score_filtered_path,
                fields=("source_provider_parsed_artifact_id",),
                errors=errors,
                error_code="hmmer_score_filter_provenance_incomplete",
            )

    scoring_result: aox_motif.ScoringResult | None = None
    scoring_alignment_path = "aox_hmm/AOX_scoring_alignment.fasta"
    if scoring_alignment_path in artifact_paths:
        try:
            scoring_result = aox_motif.score_aligned_fasta(
                artifact_text_by_path.get(scoring_alignment_path, ""),
            )
        except aox_motif.ScientificPrerequisiteError as exc:
            _s15_aox_error(
                errors,
                "motif_scoring_recalculation_failed",
                path=scoring_alignment_path,
                scientific_error=exc.to_dict(),
            )
        if scoring_result is not None:
            for record in scoring_result.alignment.records:
                if (
                    any(
                        marker in record.aligned_sequence
                        or marker in record.description.upper()
                        for marker in _S15_AOX_SYNTHETIC_MARKERS
                    )
                    or not record.sequence
                    or len(set(record.sequence)) == 1
                ):
                    _s15_aox_error(
                        errors,
                        "synthetic_sequence_evidence_forbidden",
                        path=scoring_alignment_path,
                        sequence_id=record.sequence_id,
                    )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=scoring_alignment_path,
            fields=(
                "source_hmm_artifact_id",
                "source_hmm_digest",
                "source_scoring_input_artifact_id",
                "source_scoring_input_digest",
                "alignment_operation_artifact_ids",
            ),
            errors=errors,
            error_code="motif_alignment_provenance_incomplete",
        )
        alignment_metadata = metadata_by_path.get(scoring_alignment_path, {})
        if (
            alignment_metadata.get("reference_accession")
            != aox_motif.REFERENCE_ACCESSION
        ):
            _s15_aox_error(
                errors,
                "motif_alignment_reference_mismatch",
                path=scoring_alignment_path,
                expected=aox_motif.REFERENCE_ACCESSION,
                actual=alignment_metadata.get("reference_accession"),
            )
        expected_alignment_metadata = {
            "source_hmm_digest": hmm_digest,
            "source_scoring_input_digest": (
                scoring_input_result.output_digest
                if scoring_input_result is not None
                else _s15_aox_content_digest(scoring_input_text)
            ),
        }
        _s15_aox_validate_metadata_values(
            metadata_by_path,
            path=scoring_alignment_path,
            expected=expected_alignment_metadata,
            errors=errors,
            error_code="motif_alignment_input_digest_mismatch",
        )
        if scoring_result is not None and scoring_input_result is not None:
            alignment_sequence_ids = {
                record.sequence_id for record in scoring_result.alignment.records
            }
            expected_sequence_ids = {
                record.sequence_id for record in scoring_input_result.records
            }
            if alignment_sequence_ids != expected_sequence_ids:
                _s15_aox_error(
                    errors,
                    "hmmalign_scoring_input_identity_mismatch",
                    path=scoring_alignment_path,
                    expected=sorted(expected_sequence_ids),
                    actual=sorted(alignment_sequence_ids),
                )

    scored_path = "aox_hmm/scored_ref_plus_hits.csv"
    if scored_path in artifact_paths:
        scored_text = artifact_text_by_path.get(scored_path, "")
        _s15_aox_parse_csv(
            scored_text,
            path=scored_path,
            expected_columns=tuple(aox_motif.CANONICAL_COLUMNS),
            errors=errors,
        )
        if scoring_result is not None and scored_text != scoring_result.to_csv():
            _s15_aox_error(
                errors,
                "motif_scoring_recalculation_mismatch",
                path=scored_path,
            )
        metadata = metadata_by_path.get(scored_path, {})
        expected_metadata = {
            "scoring_contract_id": aox_motif.CONTRACT_ID,
            "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
            "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
            "reference_accession": aox_motif.REFERENCE_ACCESSION,
        }
        if scoring_result is not None:
            expected_metadata.update(
                {
                    "input_digest": scoring_result.alignment.input_digest,
                    "alignment_digest": scoring_result.alignment.alignment_digest,
                }
            )
        for key, expected in expected_metadata.items():
            if metadata.get(key) != expected:
                _s15_aox_error(
                    errors,
                    "motif_scoring_metadata_mismatch",
                    path=scored_path,
                    field=key,
                    expected=expected,
                    actual=metadata.get(key),
                )
        if metadata.get("source_alignment_artifact_id") in (None, "", [], {}):
            _s15_aox_error(
                errors,
                "motif_scoring_provenance_incomplete",
                path=scored_path,
                missing_metadata="source_alignment_artifact_id",
            )

    filtered_rows = parsed_csv.get("aox_hmm/hits_len650_700_200.csv")
    filtered_sequences: dict[str, str] = {}
    if filtered_rows is not None:
        for row_number, row in enumerate(filtered_rows, start=2):
            accession = row["uniprot_accession"]
            sequence = row["sequence"].upper()
            if not accession or accession in filtered_sequences:
                _s15_aox_error(
                    errors,
                    "filtered_hit_identity_invalid",
                    path="aox_hmm/hits_len650_700_200.csv",
                    row=row_number,
                    uniprot_accession=accession,
                )
                continue
            if _S15_AOX_SEQUENCE_PATTERN.fullmatch(sequence) is None or any(
                marker in sequence for marker in _S15_AOX_SYNTHETIC_MARKERS
            ):
                _s15_aox_error(
                    errors,
                    "synthetic_sequence_evidence_forbidden",
                    path="aox_hmm/hits_len650_700_200.csv",
                    row=row_number,
                    sequence_id=accession,
                )
                continue
            try:
                length = int(row["length"])
                hmm_score = Decimal(row["hmm_score"])
            except (ValueError, InvalidOperation):
                _s15_aox_error(
                    errors,
                    "filtered_hit_numeric_field_invalid",
                    path="aox_hmm/hits_len650_700_200.csv",
                    row=row_number,
                )
                continue
            if (
                not hmm_score.is_finite()
                or length != len(sequence)
                or not 650 <= length <= 700
                or hmm_score <= 200
            ):
                _s15_aox_error(
                    errors,
                    "filtered_hit_threshold_or_length_mismatch",
                    path="aox_hmm/hits_len650_700_200.csv",
                    row=row_number,
                    observed_length=length,
                    sequence_length=len(sequence),
                    hmm_score=row["hmm_score"],
                )
            filtered_sequences[accession] = sequence

    if target_records is not None:
        for accession, sequence in sorted(filtered_sequences.items()):
            if target_records.get(accession) != sequence:
                _s15_aox_error(
                    errors,
                    "filtered_hit_target_sequence_mismatch",
                    path="aox_hmm/hits_len650_700_200.csv",
                    sequence_id=accession,
                )

    expected_candidates: dict[str, str] = {}
    if scoring_result is not None and filtered_rows is not None:
        score_rows = {row.sequence_id: row for row in scoring_result.rows}
        alignment_sequences = {
            record.sequence_id: record.sequence
            for record in scoring_result.alignment.records
        }
        expected_scoring_ids = set(filtered_sequences) | {aox_motif.REFERENCE_ACCESSION}
        if set(score_rows) != expected_scoring_ids:
            _s15_aox_error(
                errors,
                "motif_scoring_hit_lineage_mismatch",
                path=scoring_alignment_path,
                missing_sequence_ids=sorted(expected_scoring_ids - set(score_rows)),
                unexpected_sequence_ids=sorted(set(score_rows) - expected_scoring_ids),
            )
        for accession, sequence in sorted(filtered_sequences.items()):
            scored = score_rows.get(accession)
            if scored is None:
                continue
            if alignment_sequences.get(accession) != sequence:
                _s15_aox_error(
                    errors,
                    "motif_scoring_sequence_mismatch",
                    path=scoring_alignment_path,
                    sequence_id=accession,
                )
                continue
            if scored.passes_motif_rule:
                expected_candidates[accession] = sequence

    candidates_path = "aox_hmm/AOX_candidates.fasta"
    candidates: dict[str, str] | None = None
    if candidates_path in artifact_paths:
        candidates = _s15_aox_parse_fasta(
            artifact_text_by_path.get(candidates_path, ""),
            path=candidates_path,
            errors=errors,
            allow_empty=True,
        )
        if candidates is not None and candidates != expected_candidates:
            _s15_aox_error(
                errors,
                "motif_candidate_fasta_mismatch",
                path=candidates_path,
                expected_sequence_ids=sorted(expected_candidates),
                actual_sequence_ids=sorted(candidates),
            )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=candidates_path,
            fields=("source_scored_artifact_id", "source_alignment_artifact_id"),
            errors=errors,
            error_code="motif_candidate_provenance_incomplete",
        )

    representatives_path = "aox_hmm/AOX_candidates_cdhit85.fasta"
    representatives: dict[str, str] | None = None
    if representatives_path in artifact_paths:
        representatives = _s15_aox_parse_fasta(
            artifact_text_by_path.get(representatives_path, ""),
            path=representatives_path,
            errors=errors,
            allow_empty=True,
        )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=representatives_path,
            fields=(
                (
                    "source_candidate_fasta_artifact_id",
                    "source_membership_artifact_id",
                    "cdhit_operation_artifact_ids",
                )
                if candidates
                else (
                    "source_candidate_fasta_artifact_id",
                    "source_membership_artifact_id",
                )
            ),
            errors=errors,
            error_code="cdhit_representative_provenance_incomplete",
        )

    membership_path = "aox_hmm/AOX_candidates_cdhit85.clusters.csv"
    membership_rows: list[dict[str, str]] | None = None
    if membership_path in artifact_paths:
        membership_rows = _s15_aox_parse_csv(
            artifact_text_by_path.get(membership_path, ""),
            path=membership_path,
            expected_columns=S15_AOX_HMM_CDHIT_MEMBERSHIP_COLUMNS,
            errors=errors,
        )
        metadata = metadata_by_path.get(membership_path, {})
        if metadata.get("membership_schema_id") != "cdhit_cluster_membership@1":
            _s15_aox_error(
                errors,
                "cdhit_membership_metadata_mismatch",
                path=membership_path,
                field="membership_schema_id",
            )
        if metadata.get("source_candidate_fasta_artifact_id") in (None, "", [], {}):
            _s15_aox_error(
                errors,
                "cdhit_membership_provenance_incomplete",
                path=membership_path,
                missing_metadata="source_candidate_fasta_artifact_id",
            )
        if metadata.get("cdhit_identity_ppm") != aox_similarity.DEFAULT_THRESHOLD_PPM:
            _s15_aox_error(
                errors,
                "cdhit_membership_metadata_mismatch",
                path=membership_path,
                field="cdhit_identity_ppm",
                expected=aox_similarity.DEFAULT_THRESHOLD_PPM,
                actual=metadata.get("cdhit_identity_ppm"),
            )
        if candidates and metadata.get("cdhit_operation_artifact_ids") in (
            None,
            "",
            [],
            {},
        ):
            _s15_aox_error(
                errors,
                "cdhit_membership_provenance_incomplete",
                path=membership_path,
                missing_metadata="cdhit_operation_artifact_ids",
            )
        if not candidates:
            empty_result = execution_summary.get("empty_result")
            expected_reason = (
                str(empty_result.get("reason") or "").strip()
                if isinstance(empty_result, dict)
                else ""
            )
            if (
                metadata.get("empty_result_reason") != expected_reason
                or not expected_reason
            ):
                _s15_aox_error(
                    errors,
                    "cdhit_empty_membership_reason_mismatch",
                    path=membership_path,
                    expected=expected_reason,
                    actual=metadata.get("empty_result_reason"),
                )

    representative_ids, _ = _s15_aox_validate_cdhit_membership(
        membership_rows,
        candidates=candidates or {},
        representatives=representatives,
        errors=errors,
    )

    graph_result: aox_similarity.SimilarityGraphResult | None = None
    graph_paths = {
        candidates_path,
        membership_path,
        "aox_hmm/nodes.csv",
        "aox_hmm/edges_similarity.csv",
        "aox_hmm/similarity_graph_manifest.json",
    }
    if graph_paths <= artifact_paths:
        empty_result = execution_summary.get("empty_result")
        empty_result_reason = (
            str(empty_result.get("reason") or "").strip()
            if isinstance(empty_result, dict)
            else None
        )
        if candidates:
            empty_result_reason = None
        try:
            graph_result = aox_similarity.validate_graph_artifacts(
                artifact_text_by_path.get(candidates_path, ""),
                artifact_text_by_path.get(membership_path, ""),
                artifact_text_by_path.get("aox_hmm/nodes.csv", ""),
                artifact_text_by_path.get("aox_hmm/edges_similarity.csv", ""),
                artifact_text_by_path.get("aox_hmm/similarity_graph_manifest.json", ""),
                threshold_ppm=aox_similarity.DEFAULT_THRESHOLD_PPM,
                empty_result_reason=empty_result_reason,
            )
        except aox_motif.ScientificPrerequisiteError as exc:
            _s15_aox_error(
                errors,
                "similarity_graph_recalculation_failed",
                path="aox_hmm/similarity_graph_manifest.json",
                scientific_error=exc.to_dict(),
            )
        manifest_metadata = metadata_by_path.get(
            "aox_hmm/similarity_graph_manifest.json", {}
        )
        expected_manifest_metadata = {
            "manifest_schema_id": aox_similarity.MANIFEST_SCHEMA_ID,
            "node_schema_id": aox_similarity.NODE_SCHEMA_ID,
            "edge_schema_id": aox_similarity.EDGE_SCHEMA_ID,
            "similarity_calculation_id": aox_similarity.CALCULATION_ID,
            "similarity_calculation_digest": aox_similarity.CALCULATION_DIGEST,
            "similarity_implementation_digest": aox_similarity.IMPLEMENTATION_DIGEST,
        }
        for key, expected in expected_manifest_metadata.items():
            if manifest_metadata.get(key) != expected:
                _s15_aox_error(
                    errors,
                    "similarity_graph_metadata_mismatch",
                    path="aox_hmm/similarity_graph_manifest.json",
                    field=key,
                    expected=expected,
                    actual=manifest_metadata.get(key),
                )
        _s15_aox_require_metadata(
            metadata_by_path,
            path="aox_hmm/similarity_graph_manifest.json",
            fields=(
                "source_candidate_fasta_artifact_id",
                "source_membership_artifact_id",
                "nodes_artifact_id",
                "edges_artifact_id",
            ),
            errors=errors,
            error_code="similarity_graph_provenance_incomplete",
        )

    scientific_branch: str | None = None
    omitted_operation_roles: list[str] | None = None
    expected_empty_reason: str | None = None
    if score_filter_result is not None:
        if not score_filter_result.hits:
            scientific_branch = "hmmer_upstream_empty"
            omitted_operation_roles = [
                "candidate_alignment",
                "cdhit",
                "uniprot_fetch",
            ]
            expected_empty_reason = (
                "no_hmmer_hits"
                if score_filter_result.input_row_count == 0
                else "no_filtered_hmmer_accessions"
            )
        elif not filtered_sequences:
            scientific_branch = "length_filter_empty"
            omitted_operation_roles = ["candidate_alignment", "cdhit"]
            expected_empty_reason = "no_candidates_after_length_filter"
        elif not expected_candidates:
            scientific_branch = "motif_filter_empty"
            omitted_operation_roles = ["cdhit"]
            expected_empty_reason = "no_candidates_after_motif_filter"
        else:
            scientific_branch = "nonempty"
            omitted_operation_roles = []

    if execution_summary:
        missing_fields = sorted(
            S15_AOX_HMM_REQUIRED_SUMMARY_FIELDS - set(execution_summary)
        )
        if missing_fields:
            _s15_aox_error(
                errors,
                "invalid_execution_summary",
                path="aox_hmm/execution_summary.json",
                missing_fields=missing_fields,
            )
        expected_values: dict[str, object] = {
            "accession_count": len(AOX_HMM_ACCESSIONS),
            "ncbi_reference_accession_count": len(AOX_NCBI_ACCESSIONS),
            "filtered_hit_count": len(filtered_sequences),
            "scoring_row_count": len(scoring_result.rows)
            if scoring_result is not None
            else None,
            "candidate_count": len(expected_candidates),
            "representative_count": len(representative_ids),
            "graph_node_count": len(graph_result.nodes)
            if graph_result is not None
            else None,
            "graph_edge_count": len(graph_result.edges)
            if graph_result is not None
            else None,
            "length_filter": [650, 700],
            "hmm_score_threshold": 200,
            "motif_rule_score_threshold_tenths": aox_motif.THRESHOLD_TENTHS,
            "motif_rule_score_threshold": aox_motif.THRESHOLD_DISPLAY,
            "similarity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
            "similarity_threshold": "0.850000",
            "hmmer_database": "refprot",
            "hmmer_score_filter_contract_id": aox_hmmer.CONTRACT_ID,
            "hmmer_score_filter_contract_digest": aox_hmmer.CONTRACT_DIGEST,
            "hmmer_score_filter_implementation_digest": (
                aox_hmmer.IMPLEMENTATION_DIGEST
            ),
            "hmmer_score_filter_input_digest": (
                score_filter_result.input_digest
                if score_filter_result is not None
                else None
            ),
            "hmmer_score_filter_output_digest": (
                score_filter_result.output_digest
                if score_filter_result is not None
                else None
            ),
            "sequence_length_join_contract_id": aox_sequence_join.CONTRACT_ID,
            "sequence_length_join_contract_digest": (
                aox_sequence_join.CONTRACT_DIGEST
            ),
            "sequence_length_join_implementation_digest": (
                aox_sequence_join.IMPLEMENTATION_DIGEST
            ),
            "sequence_length_join_hits_digest": _s15_aox_content_digest(
                artifact_text_by_path.get(
                    "aox_hmm/hits_len650_700_200.csv",
                    "",
                )
            ),
            "sequence_length_join_target_digest": _s15_aox_content_digest(
                target_text
            ),
            "hmm_reference_set_selection_contract_id": (
                aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
            ),
            "hmm_reference_set_selection_contract_digest": (
                aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
            ),
            "hmm_reference_set_selection_implementation_digest": (
                aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
            ),
            "hmm_reference_set_input_digest": metadata_by_path.get(
                reference_path,
                {},
            ).get("input_digest"),
            "hmm_reference_set_output_digest": reference_digest,
            "scoring_reference_selection_contract_id": (
                aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
            ),
            "scoring_reference_selection_contract_digest": (
                aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
            ),
            "scoring_reference_selection_implementation_digest": (
                aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
            ),
            "scoring_reference_selection_input_digest": metadata_by_path.get(
                scoring_reference_path,
                {},
            ).get("input_digest"),
            "scoring_reference_output_digest": scoring_reference_digest,
            "scoring_input_assembly_contract_id": (
                aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
            ),
            "scoring_input_assembly_contract_digest": (
                aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
            ),
            "scoring_input_assembly_implementation_digest": (
                aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
            ),
            "scoring_reference_input_digest": (
                scoring_input_result.scoring_reference_input_digest
                if scoring_input_result is not None
                else None
            ),
            "post_uniprot_target_input_digest": (
                scoring_input_result.target_input_digest
                if scoring_input_result is not None
                else None
            ),
            "scoring_contract_id": aox_motif.CONTRACT_ID,
            "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
            "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
            "scoring_reference_accession": aox_motif.REFERENCE_ACCESSION,
            "scoring_input_digest": (
                scoring_input_result.output_digest
                if scoring_input_result is not None
                else None
            ),
            "scoring_alignment_input_digest": (
                scoring_result.alignment.input_digest
                if scoring_result is not None
                else None
            ),
            "scoring_alignment_digest": (
                scoring_result.alignment.alignment_digest
                if scoring_result is not None
                else None
            ),
            "cdhit_membership_schema_id": "cdhit_cluster_membership@1",
            "similarity_calculation_id": aox_similarity.CALCULATION_ID,
            "similarity_calculation_digest": aox_similarity.CALCULATION_DIGEST,
            "similarity_implementation_digest": aox_similarity.IMPLEMENTATION_DIGEST,
            "candidate_graph_manifest_schema_id": aox_similarity.MANIFEST_SCHEMA_ID,
            "candidate_graph_node_schema_id": aox_similarity.NODE_SCHEMA_ID,
            "candidate_graph_edge_schema_id": aox_similarity.EDGE_SCHEMA_ID,
            "candidate_graph_manifest_digest": _s15_aox_content_digest(
                artifact_text_by_path.get("aox_hmm/similarity_graph_manifest.json", "")
            ),
            "scientific_outcome": "candidates_found"
            if expected_candidates
            else "empty",
            "scientific_branch": scientific_branch,
            "omitted_operation_roles": omitted_operation_roles,
        }
        for key, expected in expected_values.items():
            if expected is not None and execution_summary.get(key) != expected:
                _s15_aox_error(
                    errors,
                    "invalid_execution_summary_value",
                    path="aox_hmm/execution_summary.json",
                    field=key,
                    expected=expected,
                    actual=execution_summary.get(key),
                )
        for digest_field in (
            "hmm_reference_set_input_digest",
            "scoring_reference_selection_input_digest",
        ):
            if not _s15_is_digest(execution_summary.get(digest_field)):
                _s15_aox_error(
                    errors,
                    "invalid_execution_summary_digest",
                    path="aox_hmm/execution_summary.json",
                    field=digest_field,
                )
        upstream_skip_digest = execution_summary.get(
            "upstream_empty_skip_receipt_digest"
        )
        if scientific_branch == "hmmer_upstream_empty":
            if not _s15_is_digest(upstream_skip_digest):
                _s15_aox_error(
                    errors,
                    "upstream_empty_skip_receipt_digest_missing",
                    path="aox_hmm/execution_summary.json",
                )
        elif upstream_skip_digest is not None:
            _s15_aox_error(
                errors,
                "unexpected_upstream_empty_skip_receipt_digest",
                path="aox_hmm/execution_summary.json",
                scientific_branch=scientific_branch,
            )
        for count_field in (
            "accession_count",
            "ncbi_reference_accession_count",
            "filtered_hit_count",
            "scoring_row_count",
            "candidate_count",
            "representative_count",
            "graph_node_count",
            "graph_edge_count",
            "warning_count",
            "motif_rule_score_threshold_tenths",
            "similarity_threshold_ppm",
        ):
            value = execution_summary.get(count_field)
            if count_field in execution_summary and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                _s15_aox_error(
                    errors,
                    "invalid_execution_summary_type",
                    path="aox_hmm/execution_summary.json",
                    field=count_field,
                )
        normalized_paths = execution_summary.get("normalized_final_deliverable_paths")
        if (
            not isinstance(normalized_paths, list)
            or any(not isinstance(path, str) or not path for path in normalized_paths)
            or len(normalized_paths) != len(set(normalized_paths))
            or set(normalized_paths) != S15_AOX_HMM_FIXED_DELIVERABLES
        ):
            _s15_aox_error(
                errors,
                "invalid_normalized_final_deliverable_paths",
                path="aox_hmm/execution_summary.json",
            )
        artifact_ids = execution_summary.get("artifact_ids")
        if (
            not isinstance(artifact_ids, list)
            or len(artifact_ids) < len(S15_AOX_HMM_FIXED_DELIVERABLES) - 1
            or any(
                not isinstance(artifact_id, str) or not artifact_id
                for artifact_id in artifact_ids
            )
            or len(artifact_ids) != len(set(artifact_ids))
        ):
            _s15_aox_error(
                errors,
                "invalid_artifact_ids",
                path="aox_hmm/execution_summary.json",
            )
        if not execution_summary.get("provider_status") or not execution_summary.get(
            "tool_status"
        ):
            _s15_aox_error(
                errors,
                "invalid_execution_status_summary",
                path="aox_hmm/execution_summary.json",
            )
        if not expected_candidates:
            empty_result = execution_summary.get("empty_result")
            if (
                not isinstance(empty_result, dict)
                or empty_result.get("reason") != expected_empty_reason
                or empty_result.get("scientific_branch") != scientific_branch
                or empty_result.get("omitted_operation_roles")
                != omitted_operation_roles
            ):
                _s15_aox_error(
                    errors,
                    "empty_result_explanation_mismatch",
                    path="aox_hmm/execution_summary.json",
                    expected_reason=expected_empty_reason,
                    expected_scientific_branch=scientific_branch,
                    expected_omitted_operation_roles=omitted_operation_roles,
                )
            elif scientific_branch == "hmmer_upstream_empty" and empty_result.get(
                "skip_receipt_digest"
            ) != upstream_skip_digest:
                _s15_aox_error(
                    errors,
                    "upstream_empty_skip_receipt_digest_mismatch",
                    path="aox_hmm/execution_summary.json",
                )

    return {
        "passed": not errors,
        "missing_paths": missing,
        "legacy_paths": legacy_paths,
        "errors": errors,
        "candidate_count": len(expected_candidates),
        "representative_count": len(representative_ids),
        "graph_node_count": 0 if graph_result is None else len(graph_result.nodes),
        "graph_edge_count": 0 if graph_result is None else len(graph_result.edges),
        "scientific_outcome": "discovered" if expected_candidates else "empty",
        "scientific_branch": scientific_branch,
        "omitted_operation_roles": omitted_operation_roles,
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
    entry.update(
        {key: value for key, value in extra.items() if value not in (None, "", [], {})}
    )
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
        detail = (
            rootless.stderr.strip()
            or rootless.stdout.strip()
            or "rootless podman is not available"
        )
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
    image_id = inspect.stdout.strip()
    if inspect.returncode != 0 or not image_id:
        detail = (
            inspect.stderr.strip() or inspect.stdout.strip() or "image digest is empty"
        )
        return _s15_prerequisite_entry(
            name="sandbox_image",
            status="prerequisite_missing",
            error_code="sandbox_image_missing",
            hint=f"Sandbox image digest inspection failed: {detail}",
            image_ref=image_ref,
        )
    try:
        image_digest = normalize_immutable_image_id(image_id)
    except ValueError as exc:
        return _s15_prerequisite_entry(
            name="sandbox_image",
            status="prerequisite_missing",
            error_code="sandbox_image_identity_invalid",
            hint=f"Sandbox image digest inspection returned an invalid identity: {exc}",
            image_ref=image_ref,
        )
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
            required=False,
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
        ncbi_identity_hint = (
            "Set OPENZYME_NCBI_EMAIL or NCBI_EMAIL before live AOX/HMM."
        )
    checks.append(
        _s15_prerequisite_entry(
            name="ncbi_identity",
            status="ok" if ncbi_identity_hint is None else "prerequisite_missing",
            error_code=None
            if ncbi_identity_hint is None
            else "live_prerequisite_missing",
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
            "ncbi_identity",
            "uniprot_http",
            "ebi_hmmer_rest_refprot",
            "s14_hpc_bio_tools",
            "hpc_runner_config",
            "sandbox_image",
            "staging_fetch_output_validation",
        ],
        "enrichment": ["semantic_scholar", "tavily"],
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
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _s15_is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
    )


def _s15_prompt_digest() -> str:
    return (
        f"sha256:{hashlib.sha256(S15_AOX_HMM_FIXED_PROMPT.encode('utf-8')).hexdigest()}"
    )


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
    tasks = repositories.tasks.list_by_session(session_id)
    agents = repositories.agents.list_by_session(session_id)
    task_finish_documents = {
        str(document.payload.get("task_id") or ""): document
        for document in repositories.engine_documents.list_by_session(session_id)
        if document.document_kind == "task_finish"
        and isinstance(document.payload, dict)
        and document.payload.get("task_id")
    }
    reports = repositories.reports.list_by_session(session_id)
    report_drafts = repositories.report_drafts.list_by_session(session_id)
    research_source_refs = repositories.research_source_refs.list_by_session(session_id)
    final_answer = _s15_final_answer(workspace)
    operation_trace: list[dict[str, object]] = []
    backend_run_ids: list[str | None] = []
    for operation in operations:
        backend_run_ids.extend(
            _s15_find_payload_values(operation.result_summary or {}, "backend_run_id")
        )
        backend_run_ids.extend(
            _s15_find_payload_values(
                operation.adapter_result_envelope or {}, "backend_run_id"
            )
        )
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
                "planned_fetch_intent_digest": _s15_digest(
                    operation.planned_fetch_intent or {}
                ),
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
    sandbox_workspace_ids = [
        workspace_record.sandbox_workspace_id for workspace_record in sandbox_workspaces
    ]
    evidence_bundle: dict[str, object] = {
        "fixed_prompt_digest": f"sha256:{hashlib.sha256(prompt.encode('utf-8')).hexdigest()}",
        "config_snapshot_digest": _s15_config_snapshot_digest(
            scenario_id=scenario_id,
            prerequisite_report=prerequisite_report,
        ),
        "session_id": session_id,
        "participant_roles": sorted(
            {agent.role for agent in agents if agent.role != "master"}
        ),
        "task_receipts": [
            {
                "task_id": task.task_id,
                "kind": task.kind,
                "status": task.status.value,
                "assigned_ref": task.assigned_ref,
                "finish_ref": (
                    task_finish_documents[task.task_id].document_id
                    if task.task_id in task_finish_documents
                    else None
                ),
                "finish_payload_digest": (
                    _s15_digest(task_finish_documents[task.task_id].payload)
                    if task.task_id in task_finish_documents
                    else None
                ),
                "finished_by": (
                    task_finish_documents[task.task_id].payload.get("finished_by")
                    if task.task_id in task_finish_documents
                    else None
                ),
                "evidence_refs": (
                    list(
                        task_finish_documents[task.task_id].payload.get("evidence_refs")
                        or []
                    )
                    if task.task_id in task_finish_documents
                    else []
                ),
            }
            for task in tasks
        ],
        "research_source_receipts": [
            {
                "source_ref_id": source.source_ref_id,
                "provider": source.provider,
                "pmid": source.pmid,
                "doi": source.doi,
                "request_digest": source.request_digest,
                "response_digest": source.response_digest,
                "provider_provenance_digest": _s15_digest(
                    source.provider_provenance or {}
                ),
                "evidence_artifact_id": source.evidence_artifact_id,
            }
            for source in research_source_refs
        ],
        "report_draft_receipts": [
            {
                "draft_id": draft.draft_id,
                "task_id": draft.task_id,
                "owner_agent_id": draft.owner_agent_id,
                "status": draft.status.value,
                "content_ref": draft.content_ref,
                "published_report_id": draft.published_report_id,
            }
            for draft in report_drafts
        ],
        "report_receipts": [
            {
                "report_id": report.report_id,
                "task_id": report.task_id,
                "status": report.status.value,
                "artifact_id": report.artifact_id,
            }
            for report in reports
        ],
        "sandbox_workspace_id": sandbox_workspace_ids[0]
        if sandbox_workspace_ids
        else None,
        "sandbox_workspaces": [
            {
                "sandbox_workspace_id": sandbox_workspace.sandbox_workspace_id,
                "agent_member_id": sandbox_workspace.agent_member_id,
                "status": sandbox_workspace.status.value,
                "image_digest": sandbox_workspace.image_digest,
                "image_version": sandbox_workspace.image_version,
                "sandbox_protocol_version": sandbox_workspace.sandbox_protocol_version,
                "manifest_version": sandbox_workspace.manifest_version,
                "source_code_artifact_ids": list(
                    sandbox_workspace.source_code_artifact_ids
                ),
                "registered_artifact_ids": list(
                    sandbox_workspace.registered_artifact_ids
                ),
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
        "route_policy_ids": _s15_non_empty_unique(
            [operation.route_policy_id for operation in operations]
        ),
        "toolchain_ids": _s15_non_empty_unique(
            [operation.toolchain_id for operation in operations]
        ),
        "runtime_packaging_ids": _s15_non_empty_unique(
            [operation.runtime_packaging_id for operation in operations]
        ),
        "provider_config_digests": _s15_non_empty_unique(
            [operation.provider_config_digest for operation in operations]
        ),
        "selected_backends": _s15_non_empty_unique(
            [operation.selected_backend for operation in operations]
        ),
        "approval_ids": _s15_non_empty_unique(
            [approval.approval_id for approval in approvals]
        ),
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
        "final_answer_digest": None
        if final_answer is None
        else _s15_digest({"content": final_answer}),
    }
    return evidence_bundle


def _s15_validate_evidence_bundle(
    evidence_bundle: dict[str, object],
) -> dict[str, object]:
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
        key
        for key in required_non_empty
        if evidence_bundle.get(key) in (None, "", [], {})
    )
    errors: list[dict[str, object]] = []
    if missing_fields:
        errors.append(
            {"error_code": "live_evidence_incomplete", "missing_fields": missing_fields}
        )
    operation_trace = evidence_bundle.get("operation_trace")
    if isinstance(operation_trace, list):
        for operation in operation_trace:
            if not isinstance(operation, dict):
                errors.append(
                    {
                        "error_code": "live_evidence_incomplete",
                        "invalid_operation_trace": True,
                    }
                )
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
        errors.append(
            {"error_code": "live_evidence_incomplete", "invalid_operation_trace": True}
        )
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
    participant_roles = set(evidence_bundle.get("participant_roles") or [])
    required_roles = {"researcher", "executor", "reporter"}
    missing_roles = sorted(required_roles - participant_roles)
    if missing_roles:
        errors.append(
            {
                "error_code": "live_product_roles_incomplete",
                "missing_roles": missing_roles,
            }
        )
    task_receipts = evidence_bundle.get("task_receipts")
    completed_task_kinds = {
        str(receipt.get("kind") or "")
        for receipt in task_receipts or []
        if isinstance(receipt, dict)
        and receipt.get("status") == "completed"
        and receipt.get("finish_ref")
        and receipt.get("finish_payload_digest")
        and receipt.get("finished_by")
    }
    required_task_kinds = {"research", "execution", "reporting"}
    missing_task_exits = sorted(required_task_kinds - completed_task_kinds)
    if missing_task_exits:
        errors.append(
            {
                "error_code": "live_task_business_exit_incomplete",
                "missing_task_kinds": missing_task_exits,
            }
        )
    source_receipts = evidence_bundle.get("research_source_receipts")
    pubmed_receipts = [
        receipt
        for receipt in source_receipts or []
        if isinstance(receipt, dict)
        and receipt.get("provider") == "pubmed"
        and isinstance(receipt.get("pmid"), str)
        and str(receipt.get("pmid") or "").isdigit()
        and _s15_is_digest(receipt.get("request_digest"))
        and _s15_is_digest(receipt.get("response_digest"))
        and receipt.get("evidence_artifact_id")
    ]
    if not pubmed_receipts:
        errors.append({"error_code": "live_pubmed_evidence_missing"})
    report_receipts = evidence_bundle.get("report_receipts")
    publishable_reports = {
        str(report.get("report_id") or "")
        for report in report_receipts or []
        if isinstance(report, dict)
        and report.get("status") in {"ready", "published"}
        and report.get("artifact_id")
    }
    report_drafts = evidence_bundle.get("report_draft_receipts")
    if not any(
        isinstance(draft, dict)
        and draft.get("status") == "published"
        and draft.get("published_report_id") in publishable_reports
        for draft in report_drafts or []
    ):
        errors.append({"error_code": "live_published_report_missing"})
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
    approved_ids = (
        {
            item.get("approval_id")
            for item in approval_trace
            if isinstance(item, dict) and item.get("status") == "approved"
        }
        if isinstance(approval_trace, list)
        else set()
    )
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
    missing_route_policy_ids = sorted(
        required_route_policy_ids - observed_route_policy_ids
    )
    if missing_route_policy_ids:
        errors.append(
            {
                "error_code": "live_evidence_incomplete",
                "missing_route_policy_ids": missing_route_policy_ids,
            }
        )
    elif isinstance(operation_trace, list):
        completed_route_policy_ids = {
            str(operation.get("route_policy_id") or "")
            for operation in operation_trace
            if isinstance(operation, dict)
            and operation.get("status") == "completed"
            and operation.get("approval_id") in approved_ids
        }
        incomplete_route_policy_ids = sorted(
            required_route_policy_ids - completed_route_policy_ids
        )
        if incomplete_route_policy_ids:
            errors.append(
                {
                    "error_code": "live_required_operation_incomplete",
                    "route_policy_ids": incomplete_route_policy_ids,
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


def _aox_hmm_final_source() -> str:
    return f"""from pathlib import Path
import hashlib
import json

from openzyme_pipeline import aox_hmmer, aox_motif, aox_reference, aox_sequence_join, aox_similarity, artifacts, bio, bio_tools, hpc


AOX_HMM_ACCESSIONS = {list(AOX_HMM_ACCESSIONS)!r}
AOX_NCBI_ACCESSIONS = {list(AOX_NCBI_ACCESSIONS)!r}
OUTPUT = Path("/openzyme/output/aox_hmm")
OUTPUT.mkdir(parents=True, exist_ok=True)


def register_text(relative_path, content, *, kind="result", format=None, required_columns=None, metadata=None):
    target = OUTPUT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    artifact_metadata = dict(metadata or {{}})
    if required_columns:
        artifact_metadata["required_columns"] = list(required_columns)
    response = artifacts.register(
        str(target),
        kind=kind,
        format=format,
        metadata={{
            "fixture": True,
            "cutover_eligible": False,
            **artifact_metadata,
        }},
    )
    return response.get("artifact") or response


def fasta_for(accessions):
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    return "".join(
        f">{{accession}}\\nM"
        + "".join(
            alphabet[(index + position) % len(alphabet)]
            for position in range(662)
        )
        + "\\n"
        for index, accession in enumerate(accessions, start=1)
    )


reference = bio.ncbi_fetch_proteins(
    accessions=AOX_NCBI_ACCESSIONS,
    output_dir="/workspace/output/bio/ncbi",
    fields=["definition", "organism", "length"],
)


def artifact_id_by_suffix(result, suffix):
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list):
        summary = result.get("result_summary")
        if isinstance(summary, dict):
            artifacts = summary.get("artifacts")
            if not isinstance(artifacts, list):
                transcript = summary.get("transcript_manifest")
                artifacts = (
                    transcript.get("files", [])
                    if isinstance(transcript, dict)
                    else []
                )
        else:
            artifacts = []
    for artifact in artifacts:
        if str(artifact.get("relative_path", "")).endswith(suffix):
            return artifact["artifact_id"]
    raise RuntimeError(f"Missing expected artifact suffix: {{suffix}}")


def operation_artifact_ids(result):
    summary = result.get("result_summary")
    transcript = summary.get("transcript_manifest") if isinstance(summary, dict) else None
    files = transcript.get("files", []) if isinstance(transcript, dict) else []
    return [item["artifact_id"] for item in files if item.get("artifact_id")]


reference_fasta_id = artifact_id_by_suffix(reference, "provider_parsed/proteins.fasta")
reference_metadata_id = artifact_id_by_suffix(reference, "provider_parsed/proteins.metadata.json")
ncbi_reference_path = artifacts.materialize(
    reference_fasta_id,
    target="/workspace/input/aox_ncbi_exact14.fasta",
)
ncbi_reference_bytes = Path(ncbi_reference_path).read_bytes()
hmm_reference_selection = aox_reference.select_hmm_reference_set(
    ncbi_reference_bytes
)
scoring_reference_selection = aox_reference.select_scoring_reference(
    ncbi_reference_bytes
)
shared_reference_metadata = {{
    "source_ncbi_fasta_artifact_id": reference_fasta_id,
    "provider_request_ids": list(reference.get("artifact_ids") or []),
    "ncbi_reference_accessions": list(AOX_NCBI_ACCESSIONS),
}}
hmm_reference_fasta = register_text(
    "AOX_ref21.fasta",
    hmm_reference_selection.to_fasta(),
    kind="sequence",
    format="fasta",
    metadata={{
        **hmm_reference_selection.metadata(),
        **shared_reference_metadata,
        "accession_count": len(AOX_HMM_ACCESSIONS),
    }},
)
scoring_reference_fasta = register_text(
    "AOX_coordinate_reference_AAB57849.1.fasta",
    scoring_reference_selection.to_fasta(),
    kind="sequence",
    format="fasta",
    metadata={{
        **scoring_reference_selection.metadata(),
        **shared_reference_metadata,
    }},
)

ws = hpc.workspace("aox_hmm")


def stage(artifact_id, path):
    return ws.stage_artifact(artifact_id, workspace_path=path)


def fetch(run):
    return ws.fetch_outputs(run)


hmm_reference_fasta_remote = stage(
    hmm_reference_fasta["artifact_id"],
    "inputs/AOX_ref21.fasta",
)
alignment = fetch(bio_tools.mafft(
    input_fasta=hmm_reference_fasta_remote,
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
hmmer_provider = bio.hmmer_search(
    hmm_artifact_id=hmm["registered_artifact_ids"][0],
    hmm_artifact_digest=hmm_remote["artifact_digest"],
    database="refprot",
    output_dir="/workspace/output/bio/hmmer",
    params={{"evalue": "1e-20", "query": "aox"}},
)
candidates = ["P12345", "Q9H9K5", "O14920", "P69905", "Q8N158"]
hits_raw_rows = [",".join(aox_hmmer.INPUT_COLUMNS)]
hits_filtered_rows = ["target,uniprot_accession,hmm_score,evalue,length,sequence"]
fixture_scoring_rows = ["fixture_sequence_id,fixture_score"]
fixture_nodes = ["fixture_node_id,fixture_value"]
fixture_edges = ["fixture_source,fixture_target,fixture_value"]
for index, accession in enumerate(candidates, start=1):
    hmm_score = 240 - index
    fixture_score = 40 - index
    sequence = f"MSEQUENCE{{index}}AOX"
    evalue = f"1e-{{20 + index}}"
    raw_page_digest = "sha256:" + hashlib.sha256(b"fixture-page-1").hexdigest()
    raw_hit_digest = "sha256:" + hashlib.sha256(
        f"fixture-hit-{{index}}".encode("utf-8")
    ).hexdigest()
    parsed_material = {{
        "target": f"target_{{index}}",
        "accession": accession,
        "evalue": evalue,
        "score": str(hmm_score),
        "page": 1,
        "hit_index": index - 1,
        "evalue_numeric": evalue.upper(),
        "score_numeric": str(hmm_score),
        "raw_page_digest": raw_page_digest,
        "raw_hit_digest": raw_hit_digest,
    }}
    parsed_row_digest = "sha256:" + hashlib.sha256(
        (json.dumps(parsed_material, sort_keys=True, indent=2) + "\\n").encode("utf-8")
    ).hexdigest()
    hits_raw_rows.append(
        ",".join(
            [
                parsed_material["target"],
                accession,
                evalue,
                str(hmm_score),
                "1",
                str(index - 1),
                evalue.upper(),
                str(hmm_score),
                raw_page_digest,
                raw_hit_digest,
                parsed_row_digest,
            ]
        )
    )
    hits_filtered_rows.append(f"target_{{index}},{{accession}},{{hmm_score}},1e-{{20 + index}},{{650 + index}},{{sequence}}")
    fixture_scoring_rows.append(f"{{accession}},{{fixture_score}}")
    fixture_nodes.append(f"{{accession}},{{fixture_score}}")
for left, right in zip(candidates, candidates[1:]):
    fixture_edges.append(f"{{left}},{{right}},0.91")

target_fasta_content = fasta_for(candidates)
target_fasta = register_text(
    "target.fasta",
    target_fasta_content,
    kind="sequence",
    format="fasta",
    metadata={{"warning_policy": "empty_target_requires_structured_warning"}},
)
scoring_input_result = aox_reference.assemble_scoring_input(
    scoring_reference_selection.to_fasta(),
    target_fasta_content,
)
scoring_input = register_text(
    "AOX_scoring_input.fasta",
    scoring_input_result.to_fasta(),
    kind="sequence",
    format="fasta",
    metadata={{
        **scoring_input_result.metadata(),
        "source_scoring_reference_artifact_id": scoring_reference_fasta["artifact_id"],
        "source_target_fasta_artifact_id": target_fasta["artifact_id"],
    }},
)
hmmalign = fetch(bio_tools.hmmalign(
    hmm=hmm_remote,
    fasta=stage(scoring_input["artifact_id"], "inputs/AOX_scoring_input.fasta"),
    placement=ws,
    expected_outputs=[{{"path": "bio_tools/hmmalign/aligned.fasta", "kind": "sequence", "format": "fasta"}}],
))
reference_hmm = register_text(
    "AOX_ref.hmm",
    "HMMER3/f [aox_ref]\\nNAME AOX_ref\\n//\\n",
    format="hmm",
    metadata={{
        "source_reference_fasta_artifact_id": hmm_reference_fasta["artifact_id"],
        "source_reference_fasta_digest": hmm_reference_selection.output_digest,
        "mafft_artifact_ids": alignment["registered_artifact_ids"],
        "hmmbuild_artifact_ids": hmm["registered_artifact_ids"],
    }},
)
hits_raw_csv = register_text(
    "hits_raw.csv",
    "\\n".join(hits_raw_rows) + "\\n",
    format="csv",
    required_columns=list(aox_hmmer.INPUT_COLUMNS),
)
hmmer_score_filter_result = aox_hmmer.parse_and_filter_csv(
    "\\n".join(hits_raw_rows) + "\\n"
)
hmmer_score_filtered_csv = register_text(
    "hmmer_score_filtered_accessions.csv",
    hmmer_score_filter_result.to_csv(),
    format="csv",
    required_columns=list(aox_hmmer.OUTPUT_COLUMNS),
    metadata=hmmer_score_filter_result.metadata(),
)
hits_filtered_csv = register_text(
    "hits_len650_700_200.csv",
    "\\n".join(hits_filtered_rows) + "\\n",
    format="csv",
    required_columns=["target", "uniprot_accession", "hmm_score", "evalue", "length", "sequence"],
)
scoring_alignment = register_text(
    "AOX_scoring_alignment.fasta",
    ">AAB57849.1 fixture coordinate reference\\nMSEQUENCEAOX\\n" + fasta_for(candidates),
    kind="sequence",
    format="fasta",
    metadata={{"scientific_status": "fixture_non_cutover"}},
)
scored_csv = register_text(
    "scored_ref_plus_hits.csv",
    "\\n".join(fixture_scoring_rows) + "\\n",
    format="csv",
    required_columns=["fixture_sequence_id", "fixture_score"],
)
candidate_fasta = register_text(
    "AOX_candidates.fasta",
    fasta_for(candidates[:3]),
    kind="sequence",
    format="fasta",
    metadata={{"motif_rule_score_threshold_tenths": 336}},
)
candidate_cdhit85 = fetch(bio_tools.cdhit(
    input_fasta=stage(candidate_fasta["artifact_id"], "inputs/AOX_candidates.fasta"),
    placement=ws,
    expected_outputs=[
        {{"path": "bio_tools/cdhit/clustered.fasta", "kind": "sequence", "format": "fasta"}},
        {{"path": "bio_tools/cdhit/clusters.csv", "kind": "result", "format": "csv"}},
    ],
    identity=0.85,
    mode="candidate",
))
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
candidate_cdhit85_membership = register_text(
    "AOX_candidates_cdhit85.clusters.csv",
    "cluster_id,member_id,representative_id,is_representative,identity_to_representative,member_length\\n",
    format="csv",
    metadata={{
        "membership_schema_id": "cdhit_cluster_membership@1",
        "scientific_status": "fixture_non_cutover",
    }},
)
nodes_csv = register_text(
    "nodes.csv",
    "\\n".join(fixture_nodes) + "\\n",
    format="csv",
    required_columns=["fixture_node_id", "fixture_value"],
)
edges_csv = register_text(
    "edges_similarity.csv",
    "\\n".join(fixture_edges) + "\\n",
    format="csv",
    required_columns=["fixture_source", "fixture_target", "fixture_value"],
)
graph_manifest = register_text(
    "similarity_graph_manifest.json",
    '{{"scientific_status":"fixture_non_cutover"}}\\n',
    format="json",
)
summary = {{
    "accession_count": len(AOX_HMM_ACCESSIONS),
    "ncbi_reference_accession_count": len(AOX_NCBI_ACCESSIONS),
    "filtered_hit_count": len(candidates),
    "scoring_row_count": len(candidates),
    "candidate_count": len(candidates),
    "representative_count": 3,
    "graph_node_count": len(candidates),
    "graph_edge_count": max(0, len(candidates) - 1),
    "length_filter": [650, 700],
    "hmm_score_threshold": 200,
    "motif_rule_score_threshold_tenths": aox_motif.THRESHOLD_TENTHS,
    "motif_rule_score_threshold": aox_motif.THRESHOLD_DISPLAY,
    "similarity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
    "similarity_threshold": "0.850000",
    "hmmer_database": "refprot",
    "hmmer_score_filter_contract_id": aox_hmmer.CONTRACT_ID,
    "hmmer_score_filter_contract_digest": aox_hmmer.CONTRACT_DIGEST,
    "hmmer_score_filter_implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
    "hmmer_score_filter_input_digest": hmmer_score_filter_result.input_digest,
    "hmmer_score_filter_output_digest": hmmer_score_filter_result.output_digest,
    "sequence_length_join_contract_id": aox_sequence_join.CONTRACT_ID,
    "sequence_length_join_contract_digest": aox_sequence_join.CONTRACT_DIGEST,
    "sequence_length_join_implementation_digest": aox_sequence_join.IMPLEMENTATION_DIGEST,
    "sequence_length_join_hits_digest": "fixture_non_cutover",
    "sequence_length_join_target_digest": "fixture_non_cutover",
    "hmm_reference_set_selection_contract_id": aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
    "hmm_reference_set_selection_contract_digest": aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST,
    "hmm_reference_set_selection_implementation_digest": aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST,
    "hmm_reference_set_input_digest": hmm_reference_selection.input_digest,
    "hmm_reference_set_output_digest": hmm_reference_selection.output_digest,
    "scoring_reference_selection_contract_id": aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID,
    "scoring_reference_selection_contract_digest": aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST,
    "scoring_reference_selection_implementation_digest": aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST,
    "scoring_reference_selection_input_digest": scoring_reference_selection.input_digest,
    "scoring_reference_output_digest": scoring_reference_selection.output_digest,
    "scoring_input_assembly_contract_id": aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
    "scoring_input_assembly_contract_digest": aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST,
    "scoring_input_assembly_implementation_digest": aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST,
    "scoring_reference_input_digest": scoring_input_result.scoring_reference_input_digest,
    "post_uniprot_target_input_digest": scoring_input_result.target_input_digest,
    "scoring_contract_id": aox_motif.CONTRACT_ID,
    "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
    "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
    "scoring_reference_accession": aox_motif.REFERENCE_ACCESSION,
    "scoring_input_digest": scoring_input_result.output_digest,
    "scoring_alignment_input_digest": "fixture_non_cutover",
    "scoring_alignment_digest": "fixture_non_cutover",
    "cdhit_membership_schema_id": "cdhit_cluster_membership@1",
    "similarity_calculation_id": "fixture_non_cutover",
    "similarity_calculation_digest": "fixture_non_cutover",
    "similarity_implementation_digest": "fixture_non_cutover",
    "candidate_graph_manifest_schema_id": aox_similarity.MANIFEST_SCHEMA_ID,
    "candidate_graph_node_schema_id": aox_similarity.NODE_SCHEMA_ID,
    "candidate_graph_edge_schema_id": aox_similarity.EDGE_SCHEMA_ID,
    "candidate_graph_manifest_digest": "fixture_non_cutover",
    "scientific_outcome": "fixture_non_cutover",
    "scientific_branch": "fixture_non_cutover",
    "omitted_operation_roles": [],
    "upstream_empty_skip_receipt_digest": None,
    "provider_status": "fixture_non_cutover",
    "tool_status": "fixture_non_cutover",
    "fixture": True,
    "cutover_eligible": False,
    "warning_count": 0,
    "reference_fasta_artifact_id": reference_fasta_id,
    "reference_metadata_artifact_id": reference_metadata_id,
    "alignment_artifact_ids": alignment["registered_artifact_ids"],
    "hmm_artifact_ids": hmm["registered_artifact_ids"],
    "hmmalign_artifact_ids": hmmalign["registered_artifact_ids"],
    "hmmer_provider_artifact_ids": operation_artifact_ids(hmmer_provider),
    "candidate_cdhit85_artifact_ids": candidate_cdhit85["registered_artifact_ids"],
    "derived_artifact_ids": [
        hmm_reference_fasta["artifact_id"],
        scoring_reference_fasta["artifact_id"],
        scoring_input["artifact_id"],
        target_fasta["artifact_id"],
        reference_hmm["artifact_id"],
        hits_raw_csv["artifact_id"],
        hmmer_score_filtered_csv["artifact_id"],
        hits_filtered_csv["artifact_id"],
        scoring_alignment["artifact_id"],
        scored_csv["artifact_id"],
        candidate_fasta["artifact_id"],
        candidate_cdhit85_fasta["artifact_id"],
        candidate_cdhit85_membership["artifact_id"],
        nodes_csv["artifact_id"],
        edges_csv["artifact_id"],
        graph_manifest["artifact_id"],
    ],
    "artifact_ids": [],
    "normalized_final_deliverable_paths": [
        "aox_hmm/AOX_ref21.fasta",
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
        "aox_hmm/AOX_scoring_input.fasta",
        "aox_hmm/target.fasta",
        "aox_hmm/AOX_ref.hmm",
        "aox_hmm/hits_raw.csv",
        "aox_hmm/hmmer_score_filtered_accessions.csv",
        "aox_hmm/hits_len650_700_200.csv",
        "aox_hmm/AOX_scoring_alignment.fasta",
        "aox_hmm/scored_ref_plus_hits.csv",
        "aox_hmm/AOX_candidates.fasta",
        "aox_hmm/AOX_candidates_cdhit85.fasta",
        "aox_hmm/AOX_candidates_cdhit85.clusters.csv",
        "aox_hmm/nodes.csv",
        "aox_hmm/edges_similarity.csv",
        "aox_hmm/similarity_graph_manifest.json",
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
"""


class V3AOXHMMEvalInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0
        self.workflow_calls = 0

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del tools
        self.calls += 1
        if self.purpose == "v3_teammate_loop:executor":
            return self._executor_response(system_prompt, messages)
        return self._master_response(system_prompt, messages)

    def _executor_response(
        self, system_prompt: str, messages: list[object]
    ) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_aox_hmm_execution"
        if any(
            _tool_message_name(message) in {"task.update", "task.finish"}
            for message in messages
        ):
            return {
                "content": "AOX/HMM execution completed with candidate artifacts and provenance.",
                "tool_calls": [],
            }
        workspace_payload = _latest_tool_payload(
            messages,
            "sandbox.workspace.status",
        )
        source_written = any(
            _tool_message_name(message) == "sandbox.file.write" for message in messages
        )
        sandbox_executed = any(
            _tool_message_name(message) == "sandbox.exec" for message in messages
        )
        if sandbox_executed:
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
        if source_written:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_sandbox_exec",
                        "name": "sandbox.exec",
                        "args": {
                            "argv": [
                                "python",
                                "/workspace/src/aox_hmm_pipeline.py",
                            ],
                            "cwd": "/workspace/src",
                            "timeout_seconds": 120,
                        },
                    }
                ],
            }
        if workspace_payload:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_write_source",
                        "name": "sandbox.file.write",
                        "args": {
                            "path": "/workspace/src/aox_hmm_pipeline.py",
                            "content": _aox_hmm_final_source(),
                            "create_dirs": True,
                        },
                    }
                ],
            }
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_aox_workspace_status",
                    "name": "sandbox.workspace.status",
                    "args": {},
                }
            ],
        }

    def _master_response(
        self, system_prompt: str, messages: list[object]
    ) -> dict[str, object]:
        del messages
        focused_task = _focused_task_from_prompt(system_prompt)
        if (
            focused_task == "task_aox_hmm_execution"
            and "completed task_id=task_aox_hmm_execution" in system_prompt
        ):
            return {
                "content": (
                    "AOX/HMM mining completed in an explicit non-cutover fixture. The workspace "
                    "contains reference FASTA and metadata, CD-HIT/MAFFT/HMMER fixture outputs, "
                    "filtered and scored fixture candidates, nodes/edges CSV, and an execution "
                    "summary with candidate_count=5. These results are not scientific evidence."
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
                                "Use the explicitly selected AOX/HMM workflow knowledge pack. "
                                "Inspect the persistent sandbox, author the source with sandbox.file.*, "
                                "and execute it with sandbox.exec so every provider/tool operation crosses "
                                "the Host-supervised SDK approval boundary. This local scenario is an "
                                "explicit non-cutover fixture, not scientific evidence."
                            ),
                        },
                    }
                ],
            }
        return {
            "content": "AOX/HMM execution is waiting for the executor workflow.",
            "tool_calls": [],
        }


class V3AOXHMMEvalModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, V3AOXHMMEvalInvoker] = {}

    def create_structured_invoker(
        self, *, purpose: str
    ) -> V3LocalEvalStructuredInvoker:
        return V3LocalEvalStructuredInvoker(purpose)

    def create_tool_calling_invoker(self, *, purpose: str) -> V3AOXHMMEvalInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = V3AOXHMMEvalInvoker(purpose)
        return self.invokers[purpose]


class _AoxHmmFixturePreflight:
    ok = True
    message = "explicit non-cutover fixture sandbox ready"


@dataclass(slots=True)
class AoxHmmFixtureHpcExecutionAdapter:
    """Explicit non-cutover runner fixture for the local sandbox workflow eval."""

    output_root: Path
    call_count: int = 0

    def submit_execution(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ExecutionOutcome:
        self.call_count += 1
        runspec = payload.get("runspec")
        metadata = runspec.get("metadata") if isinstance(runspec, dict) else None
        declared_outputs = (
            metadata.get("declared_outputs", []) if isinstance(metadata, dict) else []
        )
        artifacts: list[ExecutionArtifactRef] = []
        for item in declared_outputs:
            if not isinstance(item, dict):
                continue
            relative_path = str(item.get("path") or "")
            if not relative_path:
                continue
            output_path = (
                self.output_root / session_id / str(self.call_count) / relative_path
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                self._content(relative_path, str(item.get("format") or "")),
                encoding="utf-8",
            )
            try:
                kind = ArtifactKind(str(item.get("kind") or "result"))
            except ValueError:
                kind = ArtifactKind.RESULT
            artifacts.append(
                ExecutionArtifactRef(
                    storage_uri=str(output_path),
                    relative_path=relative_path,
                    kind=kind,
                )
            )
        return ExecutionOutcome(
            run_id=f"fixture_hpc_{self.call_count}",
            status=RunStatus.SUCCEEDED,
            execution_mode="fixture_non_cutover",
            remote_run_dir=f"fixture://{session_id}/{self.call_count}",
            raw_result={
                "status": "completed",
                "fixture": True,
                "cutover_eligible": False,
                "exit_code": 0,
            },
            artifacts=tuple(artifacts),
            exit_code=0,
        )

    def _content(self, relative_path: str, format_value: str) -> str:
        normalized_format = format_value.casefold()
        alphabet = "ACDEFGHIKLMNPQRSTVWY"
        fixture_candidates = ("P12345", "Q9H9K5", "O14920")

        def fixture_sequence(accession: str) -> str:
            seed = sum(ord(char) for char in accession)
            return "M" + "".join(
                alphabet[(seed + index) % len(alphabet)] for index in range(59)
            )

        def fixture_candidate_sequence(accession: str) -> str:
            accession_index = fixture_candidates.index(accession) + 1
            return "M" + "".join(
                alphabet[(accession_index + position) % len(alphabet)]
                for position in range(662)
            )

        if "bio_tools/cdhit/" in relative_path and relative_path.endswith(".csv"):
            header = (
                "cluster_id,member_id,representative_id,is_representative,"
                "identity_to_representative,member_length\n"
            )
            rows = "".join(
                f"cluster_{index},{accession},{accession},true,1.000000,663\n"
                for index, accession in enumerate(fixture_candidates)
            )
            return header + rows
        if "bio_tools/cdhit/" in relative_path and relative_path.endswith(".fasta"):
            return "".join(
                f">{accession} fixture\n{fixture_candidate_sequence(accession)}\n"
                for accession in fixture_candidates
            )
        if normalized_format in {"fasta", "fa", "faa", "afa"} or relative_path.endswith(
            (".fasta", ".fa", ".faa", ".afa")
        ):
            return "".join(
                f">{accession} fixture\n{fixture_sequence(accession)}\n"
                for accession in AOX_HMM_ACCESSIONS
            )
        if normalized_format == "hmm" or relative_path.endswith(".hmm"):
            return "HMMER3/f [fixture-non-cutover]\nNAME AOX_fixture\n//\n"
        if normalized_format == "csv" or relative_path.endswith(".csv"):
            if "cluster" in relative_path:
                header = (
                    "cluster_id,member_id,representative_id,is_representative,"
                    "identity_to_representative,member_length\n"
                )
                rows = "".join(
                    f"cluster_{index},{accession},{accession},true,1.000000,60\n"
                    for index, accession in enumerate(AOX_HMM_ACCESSIONS)
                )
                return header + rows
            return "target,accession,evalue,score\nfixture_1,FIXTURE1,1e-20,250\n"
        return "fixture_non_cutover\n"


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
                "accessions": list(AOX_NCBI_ACCESSIONS),
                "fields": ["definition", "organism", "length"],
                "output_dir": "/workspace/output/bio/ncbi",
            },
        )

        def artifact_id_by_suffix(result: dict[str, Any], suffix: str) -> str:
            for artifact in list(result.get("artifacts") or []):
                if str(artifact.get("relative_path") or "").endswith(suffix):
                    return str(artifact["artifact_id"])
            raise RuntimeError(f"Missing expected artifact suffix: {suffix}")

        reference_fasta_id = artifact_id_by_suffix(
            reference, "provider_parsed/proteins.fasta"
        )
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

        reference_remote = stage(reference_fasta_id, "inputs/AOX_ref21.fasta")
        alignment_remote = reference_remote
        alignment = fetch(
            control_handler(
                "bio_tools.mafft",
                {
                    "input_fasta": alignment_remote,
                    "placement": workspace,
                    "expected_outputs": [
                        {"path": "bio_tools/mafft/alignment.fasta", "kind": "sequence"}
                    ],
                    "params": {},
                },
            )
        )
        hmm = fetch(
            control_handler(
                "bio_tools.hmmbuild",
                {
                    "alignment": stage(
                        alignment["registered_artifact_ids"][0],
                        "inputs/alignment.fasta",
                    ),
                    "placement": workspace,
                    "expected_outputs": [
                        {"path": "bio_tools/hmmbuild/model.hmm", "kind": "result"}
                    ],
                    "params": {},
                },
            )
        )
        hmm_remote = stage(hmm["registered_artifact_ids"][0], "inputs/model.hmm")
        scoring_input_remote = stage(
            reference_fasta_id,
            "inputs/AOX_scoring_input.fasta",
        )
        fetch(
            control_handler(
                "bio_tools.hmmalign",
                {
                    "hmm": hmm_remote,
                    "fasta": scoring_input_remote,
                    "placement": workspace,
                    "expected_outputs": [
                        {"path": "bio_tools/hmmalign/aligned.fasta", "kind": "sequence"}
                    ],
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
                        {
                            "path": "bio_tools/cdhit/clustered.fasta",
                            "kind": "sequence",
                            "format": "fasta",
                        },
                        {
                            "path": "bio_tools/cdhit/clusters.csv",
                            "kind": "result",
                            "format": "csv",
                        },
                    ],
                    "identity": 0.85,
                    "mode": "candidate",
                },
            )
        )

        output_dir = (
            Path(tempfile.gettempdir()) / "openzyme-aox-hmm-fixture" / invocation_id
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        candidates = ("P12345", "Q9H9K5", "O14920", "P69905", "Q8N158")

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

        hits_raw_rows = [",".join(aox_hmmer.INPUT_COLUMNS)]
        hits_filtered_rows = [
            "target,uniprot_accession,hmm_score,evalue,length,sequence"
        ]
        fixture_scoring_rows = ["fixture_sequence_id,fixture_score"]
        fixture_nodes = ["fixture_node_id,fixture_value"]
        fixture_edges = ["fixture_source,fixture_target,fixture_value"]
        for index, accession in enumerate(candidates, start=1):
            hmm_score = 240 - index
            fixture_score = 40 - index
            sequence = f"MSEQUENCE{index}AOX"
            evalue = f"1e-{20 + index}"
            raw_page_digest = (
                "sha256:" + hashlib.sha256(b"fixture-page-1").hexdigest()
            )
            raw_hit_digest = "sha256:" + hashlib.sha256(
                f"fixture-hit-{index}".encode("utf-8")
            ).hexdigest()
            parsed_material = {
                "target": f"target_{index}",
                "accession": accession,
                "evalue": evalue,
                "score": str(hmm_score),
                "page": 1,
                "hit_index": index - 1,
                "evalue_numeric": evalue.upper(),
                "score_numeric": str(hmm_score),
                "raw_page_digest": raw_page_digest,
                "raw_hit_digest": raw_hit_digest,
            }
            parsed_row_digest = "sha256:" + hashlib.sha256(
                (json.dumps(parsed_material, sort_keys=True, indent=2) + "\n").encode(
                    "utf-8"
                )
            ).hexdigest()
            hits_raw_rows.append(
                ",".join(
                    [
                        parsed_material["target"],
                        accession,
                        evalue,
                        str(hmm_score),
                        "1",
                        str(index - 1),
                        evalue.upper(),
                        str(hmm_score),
                        raw_page_digest,
                        raw_hit_digest,
                        parsed_row_digest,
                    ]
                )
            )
            hits_filtered_rows.append(
                f"target_{index},{accession},{hmm_score},1e-{20 + index},{650 + index},{sequence}"
            )
            fixture_scoring_rows.append(f"{accession},{fixture_score}")
            fixture_nodes.append(f"{accession},{fixture_score}")
        for left, right in zip(candidates, candidates[1:]):
            fixture_edges.append(f"{left},{right},0.91")
        hits_raw_csv = "\n".join(hits_raw_rows) + "\n"
        hmmer_score_filter_result = aox_hmmer.parse_and_filter_csv(hits_raw_csv)
        artifacts = (
            write_artifact(
                "AOX_ref21.fasta",
                fasta_for(AOX_HMM_ACCESSIONS),
                kind=ArtifactKind.SEQUENCE,
                metadata={
                    "format": "fasta",
                    "accession_count": len(AOX_HMM_ACCESSIONS),
                    "contract_id": (
                        aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
                    ),
                    "contract_digest": (
                        aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
                    ),
                    "implementation_digest": (
                        aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
                    ),
                    "provider_request_ids": list(reference["artifact_ids"]),
                    "ncbi_reference_accessions": list(AOX_NCBI_ACCESSIONS),
                },
            ),
            write_artifact(
                "AOX_coordinate_reference_AAB57849.1.fasta",
                ">AAB57849.1\nMSEQUENCEAOX\n",
                kind=ArtifactKind.SEQUENCE,
                metadata={
                    "format": "fasta",
                    "contract_id": (
                        aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
                    ),
                    "contract_digest": (
                        aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
                    ),
                    "implementation_digest": (
                        aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
                    ),
                    "scientific_status": "fixture_non_cutover",
                },
            ),
            write_artifact(
                "AOX_scoring_input.fasta",
                ">AAB57849.1\nMSEQUENCEAOX\n" + fasta_for(candidates),
                kind=ArtifactKind.SEQUENCE,
                metadata={
                    "format": "fasta",
                    "contract_id": aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
                    "contract_digest": (
                        aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
                    ),
                    "implementation_digest": (
                        aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
                    ),
                    "scientific_status": "fixture_non_cutover",
                },
            ),
            write_artifact(
                "target.fasta",
                fasta_for(candidates),
                kind=ArtifactKind.SEQUENCE,
                metadata={
                    "format": "fasta",
                    "warning_policy": "empty_target_requires_structured_warning",
                },
            ),
            write_artifact(
                "AOX_ref.hmm",
                "HMMER3/f [fixture]\nNAME AOX_ref\n//\n",
                metadata={
                    "format": "hmm",
                    "source_reference_fasta_artifact_id": reference_fasta_id,
                    "source_reference_fasta_digest": "fixture_non_cutover",
                    "mafft_artifact_ids": list(alignment["registered_artifact_ids"]),
                    "hmmbuild_artifact_ids": list(hmm["registered_artifact_ids"]),
                },
            ),
            write_artifact(
                "hits_raw.csv",
                hits_raw_csv,
                metadata={
                    "format": "csv",
                    "required_columns": list(aox_hmmer.INPUT_COLUMNS),
                },
            ),
            write_artifact(
                "hmmer_score_filtered_accessions.csv",
                hmmer_score_filter_result.to_csv(),
                metadata={
                    "format": "csv",
                    "required_columns": list(aox_hmmer.OUTPUT_COLUMNS),
                    **hmmer_score_filter_result.metadata(),
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
                "AOX_scoring_alignment.fasta",
                ">AAB57849.1 fixture coordinate reference\nMSEQUENCEAOX\n"
                + fasta_for(candidates),
                kind=ArtifactKind.SEQUENCE,
                metadata={
                    "format": "fasta",
                    "scientific_status": "fixture_non_cutover",
                },
            ),
            write_artifact(
                "scored_ref_plus_hits.csv",
                "\n".join(fixture_scoring_rows) + "\n",
                metadata={
                    "format": "csv",
                    "required_columns": ["fixture_sequence_id", "fixture_score"],
                },
            ),
            write_artifact(
                "AOX_candidates.fasta",
                fasta_for(candidates[:3]),
                kind=ArtifactKind.SEQUENCE,
                metadata={"format": "fasta", "motif_rule_score_threshold_tenths": 336},
            ),
            write_artifact(
                "AOX_candidates_cdhit85.fasta",
                fasta_for(candidates[:3]),
                kind=ArtifactKind.SEQUENCE,
                metadata={
                    "format": "fasta",
                    "tool_name": "cd-hit",
                    "identity": 0.85,
                    "source_operation_artifact_ids": list(
                        cdhit85["registered_artifact_ids"]
                    ),
                },
            ),
            write_artifact(
                "AOX_candidates_cdhit85.clusters.csv",
                (
                    "cluster_id,member_id,representative_id,is_representative,"
                    "identity_to_representative,member_length\n"
                ),
                metadata={
                    "format": "csv",
                    "membership_schema_id": "cdhit_cluster_membership@1",
                    "scientific_status": "fixture_non_cutover",
                },
            ),
            write_artifact(
                "nodes.csv",
                "\n".join(fixture_nodes) + "\n",
                metadata={
                    "format": "csv",
                    "required_columns": ["fixture_node_id", "fixture_value"],
                },
            ),
            write_artifact(
                "edges_similarity.csv",
                "\n".join(fixture_edges) + "\n",
                metadata={
                    "format": "csv",
                    "required_columns": [
                        "fixture_source",
                        "fixture_target",
                        "fixture_value",
                    ],
                },
            ),
            write_artifact(
                "similarity_graph_manifest.json",
                '{"scientific_status":"fixture_non_cutover"}\n',
                metadata={"format": "json", "scientific_status": "fixture_non_cutover"},
            ),
            write_artifact(
                "execution_summary.json",
                json.dumps(
                    {
                        "accession_count": len(AOX_HMM_ACCESSIONS),
                        "ncbi_reference_accession_count": len(AOX_NCBI_ACCESSIONS),
                        "filtered_hit_count": len(candidates),
                        "scoring_row_count": len(candidates),
                        "candidate_count": len(candidates),
                        "representative_count": 3,
                        "graph_node_count": len(candidates),
                        "graph_edge_count": max(0, len(candidates) - 1),
                        "length_filter": [650, 700],
                        "hmm_score_threshold": 200,
                        "motif_rule_score_threshold_tenths": aox_motif.THRESHOLD_TENTHS,
                        "motif_rule_score_threshold": aox_motif.THRESHOLD_DISPLAY,
                        "similarity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
                        "similarity_threshold": "0.850000",
                        "hmmer_database": "refprot",
                        "hmmer_score_filter_contract_id": aox_hmmer.CONTRACT_ID,
                        "hmmer_score_filter_contract_digest": aox_hmmer.CONTRACT_DIGEST,
                        "hmmer_score_filter_implementation_digest": (
                            aox_hmmer.IMPLEMENTATION_DIGEST
                        ),
                        "hmmer_score_filter_input_digest": (
                            hmmer_score_filter_result.input_digest
                        ),
                        "hmmer_score_filter_output_digest": (
                            hmmer_score_filter_result.output_digest
                        ),
                        "sequence_length_join_contract_id": (
                            aox_sequence_join.CONTRACT_ID
                        ),
                        "sequence_length_join_contract_digest": (
                            aox_sequence_join.CONTRACT_DIGEST
                        ),
                        "sequence_length_join_implementation_digest": (
                            aox_sequence_join.IMPLEMENTATION_DIGEST
                        ),
                        "sequence_length_join_hits_digest": "fixture_non_cutover",
                        "sequence_length_join_target_digest": "fixture_non_cutover",
                        "hmm_reference_set_selection_contract_id": (
                            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
                        ),
                        "hmm_reference_set_selection_contract_digest": (
                            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
                        ),
                        "hmm_reference_set_selection_implementation_digest": (
                            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
                        ),
                        "hmm_reference_set_input_digest": "fixture_non_cutover",
                        "hmm_reference_set_output_digest": "fixture_non_cutover",
                        "scoring_reference_selection_contract_id": (
                            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
                        ),
                        "scoring_reference_selection_contract_digest": (
                            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
                        ),
                        "scoring_reference_selection_implementation_digest": (
                            aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
                        ),
                        "scoring_reference_selection_input_digest": (
                            "fixture_non_cutover"
                        ),
                        "scoring_reference_output_digest": "fixture_non_cutover",
                        "scoring_input_assembly_contract_id": (
                            aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
                        ),
                        "scoring_input_assembly_contract_digest": (
                            aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
                        ),
                        "scoring_input_assembly_implementation_digest": (
                            aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
                        ),
                        "scoring_reference_input_digest": "fixture_non_cutover",
                        "post_uniprot_target_input_digest": "fixture_non_cutover",
                        "scoring_contract_id": aox_motif.CONTRACT_ID,
                        "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
                        "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
                        "scoring_reference_accession": aox_motif.REFERENCE_ACCESSION,
                        "scoring_input_digest": "fixture_non_cutover",
                        "scoring_alignment_input_digest": "fixture_non_cutover",
                        "scoring_alignment_digest": "fixture_non_cutover",
                        "cdhit_membership_schema_id": "cdhit_cluster_membership@1",
                        "similarity_calculation_id": "fixture_non_cutover",
                        "similarity_calculation_digest": "fixture_non_cutover",
                        "similarity_implementation_digest": "fixture_non_cutover",
                        "candidate_graph_manifest_schema_id": aox_similarity.MANIFEST_SCHEMA_ID,
                        "candidate_graph_node_schema_id": aox_similarity.NODE_SCHEMA_ID,
                        "candidate_graph_edge_schema_id": aox_similarity.EDGE_SCHEMA_ID,
                        "candidate_graph_manifest_digest": "fixture_non_cutover",
                        "scientific_outcome": "fixture_non_cutover",
                        "scientific_branch": "fixture_non_cutover",
                        "omitted_operation_roles": [],
                        "upstream_empty_skip_receipt_digest": None,
                        "provider_status": "fixture_non_cutover",
                        "tool_status": "fixture_non_cutover",
                        "fixture": True,
                        "cutover_eligible": False,
                        "warning_count": 0,
                        "reference_artifact_ids": list(reference["artifact_ids"]),
                        "candidate_cdhit85_artifact_ids": list(
                            cdhit85["registered_artifact_ids"]
                        ),
                        "artifact_ids": [],
                        "normalized_final_deliverable_paths": sorted(
                            S15_AOX_HMM_FIXED_DELIVERABLES
                        ),
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
            execution_mode="fixture_non_cutover",
            remote_run_dir=f"fixture://{invocation_id}",
            raw_result={
                "registered_artifact_count": len(artifacts),
                "fixture": True,
                "cutover_eligible": False,
            },
            artifacts=artifacts,
            exit_code=0,
        )

    def _validate_output_content(
        self, relative_path: str, content: str, metadata: dict[str, Any]
    ) -> None:
        output_format = str(metadata.get("format") or "").lower()
        required_columns = [
            str(column) for column in list(metadata.get("required_columns") or [])
        ]
        if not content.strip():
            raise ValueError(f"fixture output is empty: {relative_path}")
        if output_format in {"fasta", "fa", "faa"} and not content.lstrip().startswith(
            ">"
        ):
            raise ValueError(f"fixture FASTA output is invalid: {relative_path}")
        if output_format == "hmm" and not content.startswith("HMMER"):
            raise ValueError(f"fixture HMM output is invalid: {relative_path}")
        if output_format == "csv" or required_columns:
            header = content.splitlines()[0].split(",") if content.splitlines() else []
            missing = [column for column in required_columns if column not in header]
            if missing:
                raise ValueError(
                    f"fixture CSV output {relative_path} is missing required columns: {missing}"
                )


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


def build_v3_eval_repository_provider(
    runtime_dir: str | Path,
) -> SQLiteRepositoryProvider:
    return SQLiteRepositoryProvider(str(Path(runtime_dir) / "control-plane.sqlite3"))


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
                json={"decision": "approved"},
            )
            resolved.raise_for_status()
            time.sleep(0.2)
            continue

        if is_ready(workspace):
            return workspace, event_text, runtime_status
        time.sleep(0.2)
    return workspace, event_text, runtime_status


S15_TASK_TERMINAL_STATUS_VALUES = {"completed", "blocked", "failed", "cancelled"}
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


def _s15_task_statuses_by_kind(workspace: dict[str, Any]) -> dict[str, set[str]]:
    statuses: dict[str, set[str]] = {}
    for item in (workspace.get("task_board") or {}).get("items", []):
        task = item.get("task") if isinstance(item, dict) else None
        if not isinstance(task, dict):
            continue
        kind = str(task.get("kind") or "")
        status = str(task.get("status") or "")
        if kind and status:
            statuses.setdefault(kind, set()).add(status)
    return statuses


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
    task_statuses = _s15_task_statuses_by_kind(workspace)
    required_task_kinds = {"research", "execution", "reporting"}
    artifact_paths = {
        artifact.relative_path
        for artifact in repositories.artifacts.list_by_session(session_id)
    }
    fixed_outputs_ready = S15_AOX_HMM_FIXED_DELIVERABLES <= artifact_paths
    sandbox_failed = any(
        run.status.value in (S15_SANDBOX_RUN_TERMINAL_STATUS_VALUES - {"completed"})
        for run in repositories.sandbox_runs.list_by_session(session_id)
    )
    operations = repositories.controlled_operations.list_by_session(session_id)
    operation_failed = any(
        operation.status.value
        in (S15_CONTROLLED_OPERATION_TERMINAL_STATUS_VALUES - {"completed"})
        for operation in operations
    )
    task_failed = any(
        status in {"blocked", "failed", "cancelled"}
        for statuses in task_statuses.values()
        for status in statuses
    )
    completed_task_kinds = {
        kind for kind, statuses in task_statuses.items() if "completed" in statuses
    }
    reports_ready = any(
        isinstance(report, dict) and report.get("status") in {"ready", "published"}
        for report in workspace.get("reports") or []
    ) and any(
        isinstance(draft, dict) and draft.get("status") == "published"
        for draft in workspace.get("report_drafts") or []
    )
    final_answer_seen = _s15_final_answer(workspace) is not None
    success_ready = bool(
        fixed_outputs_ready
        and required_task_kinds <= completed_task_kinds
        and reports_ready
        and final_answer_seen
    )
    return success_ready or sandbox_failed or operation_failed or task_failed


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
    with tempfile.TemporaryDirectory(prefix="openzyme-v3-eval-") as temp_dir:
        foundation = foundation_builder()
        if model_factory is not None:
            foundation = replace(foundation, model_factory=model_factory)
        v3_repository_provider = build_v3_eval_repository_provider(temp_dir)
        app = create_app(
            HostApiDependencies(
                foundation=foundation,
                security_policy=_eval_security_policy(),
                v3_repository_provider=v3_repository_provider,
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
            with v3_repository_provider.write() as scope:
                seed_v3_eval_execution_artifact(
                    scope.repositories,
                    "sess_eval_v3_cutover",
                )

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
    with (
        tempfile.TemporaryDirectory(prefix="openzyme-v3-aox-hmm-eval-") as temp_dir,
        ExitStack() as repository_scopes,
    ):
        foundation = foundation_builder()
        if model_factory is not None:
            foundation = replace(foundation, model_factory=model_factory)
        if use_fixture_dependencies:
            foundation = replace(
                foundation,
                execution_adapter=AoxHmmFixtureHpcExecutionAdapter(
                    Path(temp_dir) / "fixture-hpc-outputs"
                ),
            )
        v3_repository_provider = build_v3_eval_repository_provider(temp_dir)
        # Eval observation owns a non-transactional connection on the coordinator
        # thread. Host requests/background workers still get their own connections.
        v3_repositories = repository_scopes.enter_context(
            v3_repository_provider.connection_scope()
        ).repositories
        if scenario_class == "live" and prerequisite_report is not None:
            _s15_bootstrap_live_sandbox_image(v3_repositories, prerequisite_report)
        if use_fixture_dependencies:
            fixture_image = _s15_sandbox_image_prerequisite()
            if fixture_image.get("status") != "ok":
                raise RuntimeError(
                    "AOX/HMM fixture sandbox image prerequisite failed: "
                    f"{fixture_image.get('hint') or fixture_image.get('error_code')}"
                )
            v3_repositories.sandbox_images.save(
                sandbox_image_record(
                    image_ref=str(
                        fixture_image.get("image_ref") or DEFAULT_SANDBOX_IMAGE_REF
                    ),
                    image_digest=str(fixture_image["image_digest"]),
                )
            )
        dependencies_kwargs: dict[str, Any] = {
            "foundation": foundation,
            "security_policy": _eval_security_policy(),
            "v3_repository_provider": v3_repository_provider,
            "v3_background_runtime_enabled": True,
        }
        if use_fixture_dependencies:
            dependencies_kwargs.update(
                {
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
                action="v3_fixture_eval"
                if scenario_class == "fixture"
                else "v3_live_eval",
                project_id="proj_001",
                phase="evaluation",
                inputs={"scenario_id": scenario_id, "objective": objective},
                enabled=upload_results,
            ) as run:
                first_turn = client.post(
                    f"/v3/sessions/{session_id}/messages",
                    json={
                        "message": prompt,
                        "skill_keys": [S15_AOX_HMM_WORKFLOW_REF],
                    },
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
                execution_invocations = [
                    invocation
                    for invocation in v3_repositories.invocations.list_by_session(
                        session_id
                    )
                    if invocation.engine_name == "execution"
                ]
                output_artifacts = [
                    artifact
                    for artifact in artifacts
                    if artifact.invocation_id
                    and artifact.kind is not ArtifactKind.CODE
                    and artifact.relative_path != "logs/stdout.log"
                    and artifact.relative_path != "logs/stderr.log"
                ]
                projection_validation = _projection_privacy_validation(
                    workspace,
                    forbidden_value=str(Path(temp_dir)),
                )
                artifact_text_by_path: dict[str, str] = {}
                artifact_metadata_by_path: dict[str, dict[str, object]] = {}
                for artifact in artifacts:
                    if artifact.relative_path not in S15_AOX_HMM_FIXED_DELIVERABLES:
                        continue
                    artifact_metadata_by_path[artifact.relative_path] = dict(
                        artifact.metadata or {}
                    )
                    try:
                        artifact_text_by_path[artifact.relative_path] = Path(
                            artifact.storage_uri
                        ).read_text(encoding="utf-8")
                    except OSError:
                        artifact_text_by_path[artifact.relative_path] = ""
                final_output_validation = _s15_aox_validate_final_artifacts(
                    artifact_paths,
                    artifact_text_by_path,
                    artifact_metadata_by_path,
                )
                required_paths = _s15_aox_required_artifact_paths()
                evidence_bundle = _s15_build_evidence_bundle(
                    v3_repositories,
                    scenario_id=scenario_id,
                    session_id=session_id,
                    prompt=prompt,
                    prerequisite_report=prerequisite_report
                    or {"status": "ok", "required": []},
                    workspace=workspace,
                    artifacts=artifacts,
                    required_paths=required_paths,
                    final_output_validation=final_output_validation,
                )
                evidence_bundle_validation = _s15_validate_evidence_bundle(
                    evidence_bundle
                )
                has_legacy_execution_pipeline = bool(
                    execution_invocations
                ) or _s15_event_text_has_legacy_execution_pipeline(event_text)
                live_product_path_validation = _s15_validate_live_product_path(
                    evidence_bundle,
                    workspace=workspace,
                    has_legacy_execution_pipeline=has_legacy_execution_pipeline,
                )
                sandbox_workspace_id = evidence_bundle.get("sandbox_workspace_id")
                file_audit_entries = (
                    v3_repositories.file_audit_entries.list_by_workspace(
                        sandbox_workspace_id
                    )
                    if isinstance(sandbox_workspace_id, str)
                    else []
                )
                sandbox_runs = list(evidence_bundle.get("sandbox_runs") or [])
                operation_trace = list(evidence_bundle.get("operation_trace") or [])
                fixture_sandbox_complete = any(
                    isinstance(item, dict)
                    and item.get("status") == "completed"
                    and item.get("source_snapshot_artifact_id")
                    and item.get("source_tree_digest")
                    for item in sandbox_runs
                )
                fixture_operations_complete = bool(operation_trace) and all(
                    isinstance(item, dict)
                    and item.get("status") == "completed"
                    and item.get("approval_id")
                    and item.get("route_policy_id")
                    for item in operation_trace
                )
                participant_roles = set(evidence_bundle.get("participant_roles") or [])
                task_receipts = evidence_bundle.get("task_receipts") or []
                completed_task_kinds = {
                    str(item.get("kind") or "")
                    for item in task_receipts
                    if isinstance(item, dict)
                    and item.get("status") == "completed"
                    and item.get("finish_ref")
                }
                published_report_ids = {
                    str(item.get("report_id") or "")
                    for item in evidence_bundle.get("report_receipts") or []
                    if isinstance(item, dict)
                    and item.get("status") in {"ready", "published"}
                    and item.get("artifact_id")
                }
                checks = {
                    "single_user_prompt": sum(
                        1
                        for item in workspace["conversation"]
                        if item["role"] == "user"
                    )
                    == 1,
                    "delegated_executor": any(
                        item["agent"]["role"] == "executor"
                        for item in workspace["delegation"]["agents"]
                    )
                    and "task.delegate" in event_text,
                    "canonical_product_roles": {
                        "researcher",
                        "executor",
                        "reporter",
                    }
                    <= participant_roles,
                    "explicit_task_business_exits": {
                        "research",
                        "execution",
                        "reporting",
                    }
                    <= completed_task_kinds,
                    "required_pubmed_evidence": any(
                        isinstance(item, dict)
                        and item.get("provider") == "pubmed"
                        and str(item.get("pmid") or "").isdigit()
                        and item.get("evidence_artifact_id")
                        for item in evidence_bundle.get("research_source_receipts")
                        or []
                    ),
                    "published_report": bool(published_report_ids)
                    and any(
                        isinstance(item, dict)
                        and item.get("status") == "published"
                        and item.get("published_report_id") in published_report_ids
                        for item in evidence_bundle.get("report_draft_receipts") or []
                    ),
                    "source_snapshot": bool(
                        evidence_bundle.get("source_snapshot_artifact_ids")
                    )
                    and bool(evidence_bundle.get("source_snapshot_digests")),
                    "source_write_audited": any(
                        entry.operation == "write" and entry.new_digest
                        for entry in file_audit_entries
                    ),
                    "controlled_operations": fixture_operations_complete
                    if scenario_class == "fixture"
                    else bool(live_product_path_validation["passed"]),
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
                        else fixture_sandbox_complete and fixture_operations_complete
                    )
                    and any(
                        item.get("status") == "succeeded"
                        for item in workspace["capabilities"].get(
                            "execution"
                            if scenario_class == "live"
                            else "sandbox_adapter",
                            [],
                        )
                    )
                    if scenario_class == "fixture"
                    else bool(live_product_path_validation["passed"]),
                    "required_artifacts": required_paths <= artifact_paths,
                    "legacy_artifacts_excluded": not _s15_aox_legacy_paths_present(
                        artifact_paths
                    ),
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
                    "safe_projection": bool(projection_validation["passed"]),
                    "final_answer": (
                        any(
                            message.get("role") == "assistant"
                            and "candidate_count=5" in str(message.get("content") or "")
                            for message in workspace["conversation"]
                        )
                        if scenario_class == "fixture"
                        else bool(evidence_bundle.get("final_answer_available"))
                    ),
                    "background_runtime": runtime_status.get("worker_id")
                    == "host-api:background-runtime"
                    and int(runtime_status.get("processed_signal_count") or 0) > 0,
                    "legacy_pipeline_not_used": not has_legacy_execution_pipeline,
                    "sandbox_product_path": (
                        fixture_sandbox_complete and fixture_operations_complete
                        if scenario_class == "fixture"
                        else bool(live_product_path_validation["passed"])
                    ),
                    "evidence_bundle_complete": bool(
                        evidence_bundle_validation["passed"]
                    ),
                }
                live_cutover_check_names = {
                    "canonical_product_roles",
                    "explicit_task_business_exits",
                    "required_pubmed_evidence",
                    "published_report",
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
                    "projection_validation": projection_validation,
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
                        prerequisite_report=prerequisite_report
                        or {"status": "ok", "required": []},
                        evidence_payload=evidence_bundle,
                        safe_summary=safe_summary,
                    )
                result = {
                    "scenario_id": scenario_id,
                    "scenario_class": scenario_class,
                    "status": "passed" if passed else "failed",
                    "live_cutover_eligible": scenario_class == "live"
                    and all(checks.values()),
                    **live_evidence_refs,
                    "session_id": session_id,
                    "task_count": len(workspace["task_board"]["items"]),
                    "artifact_count": len(artifacts),
                    "artifact_paths": sorted(artifact_paths),
                    "required_artifact_count": len(required_paths),
                    "required_artifacts": sorted(required_paths),
                    "legacy_artifacts": _s15_aox_legacy_paths_present(artifact_paths),
                    "candidate_count": final_output_validation.get(
                        "candidate_count", 0
                    ),
                    "final_output_validation": final_output_validation,
                    "evidence_bundle": evidence_bundle,
                    "evidence_bundle_validation": evidence_bundle_validation,
                    "live_product_path_validation": live_product_path_validation,
                    "projection_validation": projection_validation,
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
    with tempfile.TemporaryDirectory(prefix="openzyme-v3-live-eval-") as temp_dir:
        foundation = build_live_eval_foundation()
        app = create_app(
            HostApiDependencies(
                foundation=foundation,
                security_policy=_eval_security_policy(),
                v3_repository_provider=build_v3_eval_repository_provider(temp_dir),
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
                    is_ready=lambda current: (
                        len((current.get("task_board") or {}).get("items", [])) >= 3
                        and any(
                            message.get("role") == "assistant"
                            for message in current.get("conversation", [])
                        )
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
    parser = argparse.ArgumentParser(description="Run OpenZyme V3 workflow evals")
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
