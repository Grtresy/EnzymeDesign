from __future__ import annotations

import argparse
import hashlib
import json
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

from .app import HostApiDependencies
from .app import create_app
from .foundation import build_configured_foundation
from .foundation import build_local_eval_foundation
from .tracing import workflow_trace


FoundationBuilder = Callable[[Path], RuntimeFoundation]


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
                        "name": "task.update",
                        "args": {"task_id": task_id, "status": "completed"},
                    }
                ],
            }
        return {"content": "Research evidence collected.", "tool_calls": []}

    def _executor_response(
        self, system_prompt: str, messages: list[object]
    ) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_eval_execution"
        if any(_tool_message_name(message) == "task.update" for message in messages):
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
                        "name": "task.update",
                        "args": {
                            "task_id": task_id,
                            "status": "completed",
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
                        "name": "task.update",
                        "args": {"task_id": task_id, "status": "completed"},
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
filtered_rows = ["accession,evalue,score,passed_filter"]
scoring_rows = ["accession,score,active_site_score,cluster_id"]
candidate_rows = ["accession,score,evalue,cluster_id"]
nodes = ["node_id,label,score,cluster_id"]
edges = ["source,target,similarity"]
for index, accession in enumerate(candidates, start=1):
    score = 120 - index
    filtered_rows.append(f"{{accession}},1e-{{20 + index}},{{score}},true")
    scoring_rows.append(f"{{accession}},{{score}},{{score - 10}},cluster_1")
    candidate_rows.append(f"{{accession}},{{score}},1e-{{20 + index}},cluster_1")
    nodes.append(f"{{accession}},candidate {{index}},{{score}},cluster_1")
for left, right in zip(candidates, candidates[1:]):
    edges.append(f"{{left}},{{right}},0.91")

filtered_fasta = register_text(
    "filtered.fasta",
    fasta_for(candidates),
    kind="sequence",
    format="fasta",
    metadata={{"validation_profile": "aox_filtered_fasta"}},
)
filtered_csv = register_text(
    "filtered.csv",
    "\\n".join(filtered_rows) + "\\n",
    format="csv",
    required_columns=["accession", "evalue", "score", "passed_filter"],
)
scoring_csv = register_text(
    "scoring.csv",
    "\\n".join(scoring_rows) + "\\n",
    format="csv",
    required_columns=["accession", "score", "active_site_score", "cluster_id"],
)
candidate_fasta = register_text(
    "candidates.fasta",
    fasta_for(candidates[:3]),
    kind="sequence",
    format="fasta",
    metadata={{"validation_profile": "aox_candidate_fasta"}},
)
candidate_csv = register_text(
    "candidates.csv",
    "\\n".join(candidate_rows[:4]) + "\\n",
    format="csv",
    required_columns=["accession", "score", "evalue", "cluster_id"],
)
candidate_cdhit85_fasta = register_text(
    "candidate_cdhit85.fasta",
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
    "candidate_count": len(candidates),
    "filter": "evalue <= 1e-20 and score >= 100",
    "reference_fasta_artifact_id": reference_fasta_id,
    "reference_metadata_artifact_id": reference_metadata_id,
    "cdhit90_artifact_ids": reference_cdhit90["registered_artifact_ids"],
    "alignment_artifact_ids": alignment["registered_artifact_ids"],
    "hmm_artifact_ids": hmm["registered_artifact_ids"],
    "hmmalign_artifact_ids": hmmalign["registered_artifact_ids"],
    "hmmer_cli_artifact_ids": hmmer_cli["registered_artifact_ids"],
    "hmmer_provider_artifact_ids": hmmer_provider["artifact_ids"],
    "candidate_cdhit85_artifact_ids": candidate_cdhit85["registered_artifact_ids"],
    "derived_artifact_ids": [
        filtered_fasta["artifact_id"],
        filtered_csv["artifact_id"],
        scoring_csv["artifact_id"],
        candidate_fasta["artifact_id"],
        candidate_csv["artifact_id"],
        candidate_cdhit85_fasta["artifact_id"],
        nodes_csv["artifact_id"],
        edges_csv["artifact_id"],
    ],
}}
register_text(
    "execution_summary.json",
    __import__("json").dumps(summary, sort_keys=True, indent=2) + "\\n",
    format="json",
    metadata={{"candidate_count": len(candidates), "filter": summary["filter"]}},
)
'''


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

    def _executor_response(self, system_prompt: str, messages: list[object]) -> dict[str, object]:
        task_id = _focused_task_from_prompt(system_prompt) or "task_aox_hmm_execution"
        if any(_tool_message_name(message) == "task.update" for message in messages):
            return {
                "content": "AOX/HMM execution completed with candidate artifacts and provenance.",
                "tool_calls": [],
            }
        if any(_tool_message_name(message) == "execution.pipeline.status" for message in messages):
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_task_complete",
                        "name": "task.update",
                        "args": {"task_id": task_id, "status": "completed"},
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
                        "id": "call_aox_execution_status",
                        "name": "execution.pipeline.status",
                        "args": {"invocation_id": invocation_id},
                    }
                ],
            }

        created_ref = _source_artifact_ref_from_payload(_latest_tool_payload(messages, "artifact.create_text"))
        patched_ref = _source_artifact_ref_from_payload(_latest_tool_payload(messages, "artifact.patch_text"))
        diffed = any(_tool_message_name(message) == "artifact.diff_text" for message in messages)
        execution_payloads = _execution_start_payloads(messages)
        dry_run_done = any(
            ":dry_run:" in str((payload.get("invocation") or {}).get("idempotency_key") if isinstance(payload.get("invocation"), dict) else "")
            for payload in execution_payloads
        )
        execute_started = any(
            ":execute:" in str((payload.get("invocation") or {}).get("idempotency_key") if isinstance(payload.get("invocation"), dict) else "")
            for payload in execution_payloads
        )

        if patched_ref is not None and dry_run_done and not execute_started:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_execute",
                        "name": "execution.pipeline.start",
                        "args": {
                            "task_id": task_id,
                            "code_artifact_id": patched_ref[0],
                            "inputs": {"approval_policy": "single_plan"},
                        },
                    }
                ],
            }
        if patched_ref is not None and diffed and not dry_run_done:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_aox_dry_run",
                        "name": "execution.pipeline.start",
                        "args": {
                            "task_id": task_id,
                            "code_artifact_id": patched_ref[0],
                            "inputs": {"approval_policy": "single_plan"},
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

        filtered_rows = ["accession,evalue,score,passed_filter"]
        scoring_rows = ["accession,score,active_site_score,cluster_id"]
        candidate_rows = ["accession,score,evalue,cluster_id"]
        nodes = ["node_id,label,score,cluster_id"]
        edges = ["source,target,similarity"]
        for index, accession in enumerate(candidates, start=1):
            score = 120 - index
            filtered_rows.append(f"{accession},1e-{20 + index},{score},true")
            scoring_rows.append(f"{accession},{score},{score - 10},cluster_1")
            candidate_rows.append(f"{accession},{score},1e-{20 + index},cluster_1")
            nodes.append(f"{accession},candidate {index},{score},cluster_1")
        for left, right in zip(candidates, candidates[1:]):
            edges.append(f"{left},{right},0.91")
        artifacts = (
            write_artifact(
                "filtered.fasta",
                fasta_for(candidates),
                kind=ArtifactKind.SEQUENCE,
                metadata={"format": "fasta"},
            ),
            write_artifact(
                "filtered.csv",
                "\n".join(filtered_rows) + "\n",
                metadata={"format": "csv", "required_columns": ["accession", "evalue", "score", "passed_filter"]},
            ),
            write_artifact(
                "scoring.csv",
                "\n".join(scoring_rows) + "\n",
                metadata={"format": "csv", "required_columns": ["accession", "score", "active_site_score", "cluster_id"]},
            ),
            write_artifact(
                "candidates.fasta",
                fasta_for(candidates[:3]),
                kind=ArtifactKind.SEQUENCE,
                metadata={"format": "fasta"},
            ),
            write_artifact(
                "candidates.csv",
                "\n".join(candidate_rows[:4]) + "\n",
                metadata={"format": "csv", "required_columns": ["accession", "score", "evalue", "cluster_id"]},
            ),
            write_artifact(
                "candidate_cdhit85.fasta",
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
                        "candidate_count": len(candidates),
                        "filter": "evalue <= 1e-20 and score >= 100",
                        "reference_artifact_ids": list(reference["artifact_ids"]),
                        "cdhit90_artifact_ids": list(cdhit90["registered_artifact_ids"]),
                        "candidate_cdhit85_artifact_ids": list(cdhit85["registered_artifact_ids"]),
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


def build_local_eval_runtime(sqlite_db_path: Path) -> RuntimeFoundation:
    settings = get_settings()
    return build_local_eval_foundation(
        sqlite_db_path=sqlite_db_path,
        settings=replace(
            settings,
            llm=replace(settings.llm, api_key=None),
        ),
    )


def build_live_eval_foundation(sqlite_db_path: Path) -> RuntimeFoundation:
    return build_configured_foundation(sqlite_db_path=sqlite_db_path)


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
        foundation = foundation_builder(Path(temp_dir) / "eval.sqlite3")
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
    scenario_id: str = "v3_aox_hmm_prompt_e2e",
) -> dict[str, Any]:
    objective = (
        "Run AOX/HMM mining from a natural language prompt using V3 task delegation, "
        "versioned source artifacts, dry-run approval, sandbox execution, and workspace artifacts."
    )
    session_id = "sess_eval_aox_hmm"
    with tempfile.TemporaryDirectory(prefix="openzyme-v3-aox-hmm-eval-") as temp_dir:
        foundation = foundation_builder(Path(temp_dir) / "eval.sqlite3")
        if model_factory is not None:
            foundation = replace(foundation, model_factory=model_factory)
        v3_repositories = build_v3_eval_repositories()
        app = create_app(
            HostApiDependencies(
                foundation=foundation,
                v3_repositories=v3_repositories,
                v3_background_runtime_enabled=True,
                v3_pipeline_sandbox_runner=AoxHmmFixtureSandboxRunner(),
                v3_bio_adapter=DeterministicBioDatabaseAdapter(),
                v3_allow_bio_fixture_adapter=True,
            )
        )
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
            prompt = (
                "Run AOX/HMM mining from only this prompt. Use these 13 AOX accessions: "
                + ", ".join(AOX_HMM_ACCESSIONS)
                + ". Build a reference HMM, search a target protein library, filter candidates, "
                "export candidate FASTA/CSV, scoring CSV, candidate clusters, nodes.csv, "
                "edges_similarity.csv, and summarize candidate count and warnings."
            )
            with workflow_trace(
                "openzyme.v3_aox_hmm_prompt_eval",
                action="v3_local_eval" if model_factory is not None else "v3_live_eval",
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
                workspace, event_text, runtime_status = _poll_v3_background_workspace(
                    client,
                    session_id=session_id,
                    timeout_seconds=45.0,
                    is_ready=lambda workspace: (
                        not workspace.get("pending_approvals")
                        and any(
                            item["task"]["task_id"] == "task_aox_hmm_execution"
                            and item["task"]["status"] == "completed"
                            for item in workspace["task_board"]["items"]
                        )
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
                required_paths = {
                    "bio/ncbi/provider_request.json",
                    "bio/ncbi/provider_observation.json",
                    "bio/ncbi/provider_parsed/proteins.fasta",
                    "bio/ncbi/provider_parsed/proteins.metadata.json",
                    "bio_tools/cdhit/clustered.fasta",
                    "bio_tools/mafft/alignment.fasta",
                    "bio_tools/hmmbuild/model.hmm",
                    "bio/hmmer/provider_request.json",
                    "bio/hmmer/provider_observation.json",
                    "bio/hmmer/provider_raw/raw_hits.json",
                    "bio/hmmer/provider_parsed/parsed_hits.csv",
                    "aox_hmm/filtered.fasta",
                    "aox_hmm/filtered.csv",
                    "aox_hmm/scoring.csv",
                    "aox_hmm/candidates.fasta",
                    "aox_hmm/candidates.csv",
                    "aox_hmm/candidate_cdhit85.fasta",
                    "aox_hmm/nodes.csv",
                    "aox_hmm/edges_similarity.csv",
                    "aox_hmm/execution_summary.json",
                }
                plan = next((payload for payload in plan_payloads if isinstance(payload, dict)), {})
                checks = {
                    "single_user_prompt": sum(1 for item in workspace["conversation"] if item["role"] == "user") == 1,
                    "delegated_executor": any(
                        item["agent"]["role"] == "executor"
                        for item in workspace["delegation"]["agents"]
                    )
                    and "task.delegate" in event_text,
                    "source_artifact_versions": sorted(
                        int((artifact.metadata or {}).get("version") or 0)
                        for artifact in code_artifacts
                    )
                    == [1, 2],
                    "source_diff_recorded": "artifact.diff_text" in event_text,
                    "dry_run_plan": bool(dry_run_invocations)
                    and bool(plan.get("bio_operations"))
                    and bool(plan.get("bio_tool_operations"))
                    and bool(plan.get("approval_requirements")),
                    "approval_resolved": "event: approval.requested" in event_text
                    and "event: approval.resolved" in event_text,
                    "execution_completed": bool(terminal_invocations)
                    and any(
                        item.get("status") == "succeeded"
                        for item in workspace["capabilities"].get("execution", [])
                    ),
                    "required_artifacts": required_paths <= artifact_paths,
                    "candidate85_artifact": any(
                        artifact.relative_path == "aox_hmm/candidate_cdhit85.fasta"
                        and (artifact.metadata or {}).get("identity") == 0.85
                        for artifact in artifacts
                    ),
                    "output_provenance": bool(output_artifacts)
                    and all(
                        (artifact.metadata or {}).get("source_code_artifact_id")
                        and (artifact.metadata or {}).get("source_code_digest")
                        for artifact in output_artifacts
                    ),
                    "safe_projection": "storage_uri" not in projected_text
                    and str(Path(temp_dir)) not in projected_text,
                    "final_answer": any(
                        message.get("role") == "assistant"
                        and "candidate_count=5" in str(message.get("content") or "")
                        for message in workspace["conversation"]
                    ),
                    "background_runtime": runtime_status.get("worker_id") == "host-api:background-runtime"
                    and int(runtime_status.get("processed_signal_count") or 0) > 0,
                }
                result = {
                    "scenario_id": scenario_id,
                    "session_id": session_id,
                    "task_count": len(workspace["task_board"]["items"]),
                    "artifact_count": len(artifacts),
                    "required_artifact_count": len(required_paths),
                    "candidate_count": 5,
                    "checks": checks,
                    "passed": all(checks.values()),
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
        foundation = build_live_eval_foundation(Path(temp_dir) / "eval.sqlite3")
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


def run_v3_live_evals(*, upload_results: bool = False) -> dict[str, Any]:
    result = _run_v3_live_task_plan_scenario(upload_results=upload_results)
    return {
        "scenario_count": 1,
        "passed": 1 if result["passed"] else 0,
        "failed": 0 if result["passed"] else 1,
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
        "--upload-results",
        action="store_true",
        help="Enable LangSmith trace upload for eval scenario runs",
    )
    args = parser.parse_args(argv)
    summary = (
        run_v3_live_evals(upload_results=args.upload_results)
        if args.live
        else run_v3_local_evals(upload_results=args.upload_results)
    )
    print(summary)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
