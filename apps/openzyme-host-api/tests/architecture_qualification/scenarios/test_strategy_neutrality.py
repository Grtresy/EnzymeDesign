from __future__ import annotations

import hashlib
from pathlib import Path
import time

import pytest

from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_cli.client import HostApiClient

from ..composition import ProductionCompositionFactory
from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..external_ports import ExternalEffectLedger
from ..oracles import assert_strategy_neutrality_oracle


_TASKS = {
    "execution": ("strategy_execution", "executor"),
    "reporting": ("strategy_reporting", "reporter"),
    "research": ("strategy_research", "researcher"),
}


def _create(kind: str) -> dict[str, object]:
    task_id, _ = _TASKS[kind]
    return {
        "id": f"create_{kind}",
        "name": "task.create",
        "args": {
            "task_id": task_id,
            "subject": f"Strategy-neutral {kind}",
            "description": "Agent-selected task ordering under real Host composition.",
            "kind": kind,
        },
    }


def _delegate(kind: str) -> dict[str, object]:
    task_id, role = _TASKS[kind]
    return {
        "id": f"delegate_{kind}",
        "name": "task.delegate",
        "args": {
            "task_id": task_id,
            "agent_role": role,
            "instructions": f"Own the {kind} task without a prescribed global phase.",
        },
    }


def _read(call_id: str) -> dict[str, object]:
    return {"id": call_id, "name": "task.list", "args": {}}


def _variant_phases() -> dict[str, tuple[tuple[dict[str, object], ...], ...]]:
    baseline = (
        tuple(_create(kind) for kind in ("research", "execution", "reporting")),
        tuple(_delegate(kind) for kind in ("research", "execution", "reporting")),
    )
    return {
        "baseline": baseline,
        "bounded_turn_split": tuple(
            (operation,)
            for operation in (
                *(_create(kind) for kind in ("research", "execution", "reporting")),
                *(_delegate(kind) for kind in ("research", "execution", "reporting")),
            )
        ),
        "early_reporting_delegation": (
            (_create("reporting"),),
            (_delegate("reporting"),),
            (_create("execution"), _create("research")),
            (_delegate("research"), _delegate("execution")),
        ),
        "inserted_read_and_prose": (
            (_read("read_before_create"),),
            baseline[0],
            (_read("read_before_delegate"),),
            baseline[1],
        ),
        "reordered_safe_actions": (
            tuple(_create(kind) for kind in ("reporting", "execution", "research")),
            tuple(_delegate(kind) for kind in ("reporting", "research", "execution")),
        ),
        "safe_rejection_followup": (
            (
                {
                    "id": "safe_missing_task_rejection",
                    "name": "task.update",
                    "args": {
                        "task_id": "missing_strategy_task",
                        "subject": "Must not dispatch",
                    },
                },
            ),
            baseline[0],
            baseline[1],
        ),
    }


class _StrategyInvoker:
    def __init__(
        self,
        purpose: str,
        phases: tuple[tuple[dict[str, object], ...], ...],
    ) -> None:
        self.purpose = purpose
        self.phases = phases
        self.calls = 0

    def invoke_with_tools(
        self,
        *,
        system_prompt: str,
        messages: list[object],
        tools: list[object],
    ) -> dict[str, object]:
        del system_prompt, messages, tools
        if self.purpose != "v3_harness_loop":
            return {"content": "Observed delegated task state.", "tool_calls": []}
        call_index = self.calls
        self.calls += 1
        if call_index % 2:
            return {
                "content": "The public world state is visible; choose the next action.",
                "tool_calls": [],
            }
        phase_index = call_index // 2
        if phase_index >= len(self.phases):
            return {"content": "Task graph already closed.", "tool_calls": []}
        return {"content": "", "tool_calls": list(self.phases[phase_index])}


class _StrategyModelFactory:
    def __init__(self, phases: tuple[tuple[dict[str, object], ...], ...]) -> None:
        self.phases = phases
        self.invokers: dict[str, _StrategyInvoker] = {}

    def create_tool_calling_invoker(self, *, purpose: str) -> _StrategyInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = _StrategyInvoker(purpose, self.phases)
        return self.invokers[purpose]


def _wait_terminal(
    public: HostApiClient,
    *,
    session_id: str,
    command_id: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 10.0
    while True:
        status = public.get_v3_runtime_command(session_id, command_id)
        if status["status"] in {"cancelled", "completed", "failed", "locked"}:
            return status
        if time.monotonic() >= deadline:
            raise AssertionError("bounded public runtime command did not settle")
        time.sleep(0.01)


def _strings(value: object) -> tuple[str, ...]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"error_code", "status"} and isinstance(item, str):
                result.append(item)
            result.extend(_strings(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_strings(item))
    return tuple(result)


@pytest.mark.architecture_qualification_scenario(
    scenario_id="strategy-neutrality.public-action-permutations",
    family="strategy-neutrality",
    selections=("full", "premerge_subset"),
)
def test_public_host_composition_preserves_ordinary_agent_strategy_space(
    tmp_path: Path,
) -> None:
    observations: dict[str, dict[str, object]] = {}
    for name, phases in _variant_phases().items():
        factory = ProductionCompositionFactory.create(tmp_path / f"strategy-{name}")
        model_factory = _StrategyModelFactory(phases)
        composition = factory.build(model_factory=model_factory)
        session_id = f"session_strategy_{name}"
        with composition:
            assert composition.client is not None
            public = HostApiClient("http://testserver", session=composition.client)
            public.create_v3_session(
                session_id=session_id,
                project_id="strategy-neutrality",
                objective="Let the model choose an ordinary legal task order.",
                title=f"Strategy neutrality {name}",
            )
            terminals: list[dict[str, object]] = []
            for phase_index in range(len(phases)):
                public.post_v3_message(
                    session_id,
                    message=f"Continue from public state for phase {phase_index + 1}.",
                )
                command = public.drain_v3_runtime(
                    session_id,
                    max_signals=8,
                    max_steps_per_agent=2,
                    idempotency_key=f"strategy:{name}:{phase_index + 1}",
                )
                terminals.append(
                    _wait_terminal(
                        public,
                        session_id=session_id,
                        command_id=str(command["command_id"]),
                    )
                )
            workspace = public.get_v3_workspace(session_id)
            events = public.get_v3_events(session_id, after_cursor=0)

        task_items = dict(workspace["task_board"])["items"]
        tasks = [dict(dict(item)["task"]) for item in task_items]
        kinds = sorted(str(task["kind"]) for task in tasks)
        assigned = [task for task in tasks if task.get("assigned_ref")]
        event_strings = _strings(events)
        phase_veto_codes = sorted(
            {
                item
                for item in event_strings
                if item == "precondition_failed"
                or item.startswith("aox_finalization_")
            }
        )
        assert all(item["status"] == "completed" for item in terminals)
        assert kinds == ["execution", "reporting", "research"]
        assert len(assigned) == 3
        if name == "safe_rejection_followup":
            assert "invalid_tool_context" in event_strings
        observations[name] = {
            "business_outcome": "assigned-three-role-task-graph",
            "canonical_task_kinds": kinds,
            "composition_reachable": True,
            "external_effect_count": factory.external_effect_ledger.count_effects(),
            "phase_veto_codes": phase_veto_codes,
            "synthetic_reachability": False,
        }

    assert_strategy_neutrality_oracle(observations)
    observation = {
        "schema_id": "openzyme_strategy_neutrality_observation@1",
        "transformations": observations,
    }
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )
    record_effect_ledger_snapshot(ExternalEffectLedger().snapshot())
