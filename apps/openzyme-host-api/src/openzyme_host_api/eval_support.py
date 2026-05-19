from __future__ import annotations

from openzyme_engines import EvidenceSynthesis
from openzyme_engines import EvidenceSynthesisItem
from openzyme_engines import ResearchBriefDraft as EngineResearchBriefDraft
from openzyme_engines import ResearchSourceItem
from openzyme_engines import ResearchSupervisorAction
from openzyme_engines import ResearchUnitDraft as EngineResearchUnitDraft
from openzyme_engines import ResearchUnitPlan as EngineResearchUnitPlan
from openzyme_runtime import ConstraintItem
from openzyme_runtime import ConstraintSet
from openzyme_runtime import DesignBriefDraft
from openzyme_runtime import DesignNextAction
from openzyme_runtime import ExecutionPlanDraft
from openzyme_runtime import IntakeClarification
from openzyme_runtime import IntakePhaseOutput
from openzyme_runtime import ReportDraft
from openzyme_runtime import ResearchBriefDraft as RuntimeResearchBriefDraft


class DeterministicLocalStructuredInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose

    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict[str, object]):
        del schema, system_prompt
        objective = str(user_payload.get("objective") or "Improve thermostability")
        if self.purpose == "intake_collect":
            return IntakePhaseOutput(
                clarification=IntakeClarification(),
                constraint_set=ConstraintSet(
                    objective_summary=objective,
                    constraints=[
                        ConstraintItem(
                            category="technical",
                            description="Prepare execution-ready artifacts.",
                        )
                    ],
                ),
                design_brief=DesignBriefDraft(
                    design_brief=f"Design brief for {objective}",
                    success_criteria=["Produce an execution-ready workspace."],
                ),
                research_brief=RuntimeResearchBriefDraft(
                    research_brief=f"Research brief for {objective}",
                    focus_areas=["evidence"],
                    expected_outputs=["canonical research summary"],
                ),
            )
        if self.purpose == "design_next_action":
            evidence_refs = list(user_payload.get("evidence_refs") or [])
            run_summary = dict(user_payload.get("run_summary") or {})
            if not evidence_refs:
                return DesignNextAction(
                    action_kind="collect_research",
                    summary="Collect evidence.",
                    rationale="No canonical evidence exists yet.",
                    arguments={},
                )
            if not run_summary:
                return DesignNextAction(
                    action_kind="request_execution",
                    summary="Request execution.",
                    rationale="Evidence and execution-ready artifacts are available.",
                    arguments={},
                )
            return DesignNextAction(
                action_kind="stop",
                summary="Stop and report.",
                rationale="The workflow has an execution result.",
                stop_reason="design_loop_complete",
                arguments={},
            )
        if self.purpose == "deep_research_brief":
            return EngineResearchBriefDraft(research_brief=f"Research brief for {objective}")
        if self.purpose == "deep_research_supervisor":
            unit_results = list(user_payload.get("unit_results") or [])
            if any(result.get("findings") for result in unit_results):
                return ResearchSupervisorAction(
                    action_kind="complete",
                    rationale="A finding exists.",
                )
            return ResearchSupervisorAction(
                action_kind="conduct_research",
                rationale="Collect one evidence unit.",
                unit_plan=EngineResearchUnitPlan(
                    units=[
                        EngineResearchUnitDraft(
                            unit_id="evidence",
                            topic="supporting evidence",
                            query=f"{objective} evidence",
                            rationale="Collect evidence for downstream design.",
                        )
                    ],
                    synthesis_goal="Support downstream design.",
                ),
            )
        if self.purpose == "deep_research_synthesis":
            return EvidenceSynthesis(
                summary="Research evidence supports the current objective.",
                evidence_items=[
                    EvidenceSynthesisItem(
                        summary="Evidence supports the current scaffold direction.",
                        query=f"{objective} evidence",
                        confidence_label="high",
                        sources=[
                            ResearchSourceItem(
                                title="Deterministic source",
                                locator="https://example.org/evidence",
                                kind="web_page",
                            )
                        ],
                    ),
                    EvidenceSynthesisItem(
                        summary="Structure-backed evidence supports execution.",
                        query=f"{objective} structure evidence",
                        confidence_label="medium",
                        sources=[
                            ResearchSourceItem(
                                title="Deterministic structure source",
                                locator="https://example.org/structure-evidence",
                                kind="web_page",
                            )
                        ],
                    ),
                ],
                unresolved_gaps=["Need wet-lab validation."],
            )
        if self.purpose == "execution_plan":
            return ExecutionPlanDraft(
                catalog_tool_id="fpocket",
                rationale="Use the curated execution-ready structure artifact.",
                tool_inputs={},
                expected_result_summary="Run fpocket on the selected structure artifact.",
            )
        if self.purpose == "report_review":
            return ReportDraft(
                title="OpenZyme design report",
                summary="The workflow completed with deterministic local evidence.",
                stage_summary="Research, execution, and report review completed.",
                key_decisions=["Proceed with the current scaffold direction."],
            )
        raise AssertionError(f"Unhandled local structured purpose {self.purpose!r}")


class DeterministicLocalToolCallingInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del system_prompt, messages, tools
        self.calls += 1
        if self.purpose == "deep_research_researcher" and self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_web_search",
                        "name": "web.search",
                        "args": {
                            "query": "thermostability evidence",
                            "topic": "supporting evidence",
                            "max_results": 1,
                        },
                    }
                ],
            }
        return {"content": "", "tool_calls": []}


class DeterministicLocalModelFactory:
    """Deterministic model implementation for local eval/test foundations only."""

    def __init__(self) -> None:
        self.tool_invokers: dict[str, DeterministicLocalToolCallingInvoker] = {}

    def create_structured_invoker(
        self, *, purpose: str
    ) -> DeterministicLocalStructuredInvoker:
        return DeterministicLocalStructuredInvoker(purpose)

    def create_tool_calling_invoker(
        self, *, purpose: str
    ) -> DeterministicLocalToolCallingInvoker:
        if purpose not in self.tool_invokers:
            self.tool_invokers[purpose] = DeterministicLocalToolCallingInvoker(purpose)
        return self.tool_invokers[purpose]
