from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import pytest

from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_cli.client import HostApiClient

from ..composition import ProductionCompositionFactory
from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..external_ports import ExternalEffectLedger
from ..oracles import assert_world_fidelity_oracle


class _WorldFidelityInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0
        self.observed_failure: dict[str, object] | None = None

    def invoke_with_tools(
        self,
        *,
        system_prompt: str,
        messages: list[object],
        tools: list[object],
    ) -> dict[str, object]:
        del system_prompt, tools
        if self.purpose != "v3_harness_loop":
            return {"content": "No delegated work was requested.", "tool_calls": []}
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "world_invalid_update",
                        "name": "task.update",
                        "args": {
                            "task_id": "world_missing_task",
                            "subject": "Must be rejected without effect",
                        },
                    }
                ],
            }
        if self.calls == 2:
            for message in reversed(messages):
                content = (
                    message.get("content")
                    if isinstance(message, dict)
                    else getattr(message, "content", "")
                )
                try:
                    payload = json.loads(str(content or ""))
                except json.JSONDecodeError:
                    continue
                if payload.get("error_code") == "invalid_tool_context":
                    self.observed_failure = dict(payload)
                    break
            assert self.observed_failure is not None
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "world_source_bound_followup",
                        "name": "task.create",
                        "args": {
                            "task_id": "world_real_task",
                            "subject": "Agent correction after typed world fact",
                            "description": "The next decision uses the real rejection.",
                            "kind": "general",
                        },
                    }
                ],
            }
        return {
            "content": "The typed rejection was visible and the corrected action succeeded.",
            "tool_calls": [],
        }


class _WorldFidelityModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, _WorldFidelityInvoker] = {}

    def create_tool_calling_invoker(self, *, purpose: str) -> _WorldFidelityInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = _WorldFidelityInvoker(purpose)
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
            raise AssertionError("world-fidelity runtime command did not settle")
        time.sleep(0.01)


def _contains_forbidden_fallback(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in {"fallback", "fallback_result", "synthetic_result"}:
                return True
            if _contains_forbidden_fallback(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_fallback(item) for item in value)
    return False


@pytest.mark.architecture_qualification_scenario(
    scenario_id="world-fidelity.earliest-cause-visible",
    family="world-fidelity",
    selections=("full", "premerge_subset"),
)
def test_typed_world_fact_reaches_next_decision_without_history_poisoning(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "world-fidelity")
    model_factory = _WorldFidelityModelFactory()
    composition = factory.build(model_factory=model_factory)
    session_id = "session_world_fidelity"
    with composition:
        assert composition.client is not None
        public = HostApiClient("http://testserver", session=composition.client)
        public.create_v3_session(
            session_id=session_id,
            project_id="world-fidelity",
            objective="Correct an action from the exact typed world fact.",
            title="World fidelity",
        )
        public.post_v3_message(
            session_id,
            message="Inspect the exact rejection and choose the correction.",
        )
        command = public.drain_v3_runtime(
            session_id,
            max_signals=1,
            max_steps_per_agent=3,
            idempotency_key="world-fidelity:single-bounded-turn",
        )
        terminal = _wait_terminal(
            public,
            session_id=session_id,
            command_id=str(command["command_id"]),
        )
        workspace = public.get_v3_workspace(session_id)
        events = public.get_v3_events(session_id, after_cursor=0)

    invoker = model_factory.invokers["v3_harness_loop"]
    delivered = invoker.observed_failure
    assert delivered is not None
    projected_failures = list(workspace["failure_observations"])
    assert len(projected_failures) == 1
    projected = dict(projected_failures[0])
    delivered_observation = dict(delivered["failure_observation"])
    task_items = list(dict(workspace["task_board"])["items"])
    tasks = [dict(dict(item)["task"]) for item in task_items]
    assert terminal["status"] == "completed"
    assert delivered["error_code"] == "invalid_tool_context"
    assert delivered_observation["source_ref"] == "world_invalid_update"
    assert projected["failure_id"] == delivered_observation["failure_id"]
    assert projected["error_code"] == delivered["error_code"]
    assert projected["source_ref"] == delivered_observation["source_ref"]
    assert [task["task_id"] for task in tasks] == ["world_real_task"]
    assert factory.external_effect_ledger.count_effects() == 0
    assert not _contains_forbidden_fallback(delivered)

    observation = {
        "automatic_recovery_count": 0,
        "earliest_typed_cause": str(delivered["error_code"]),
        "next_decision_visible_cause": str(delivered["error_code"]),
        "sealed_terminal_cause": str(projected["error_code"]),
        "source_bound": (
            projected["source_ref"] == "world_invalid_update"
            and projected["source_version"]
            == delivered_observation["source_version"]
        ),
        "synthetic_fallback": False,
        "wrapper_chain": [
            str(delivered["status"]),
            str(terminal["status"]),
        ],
    }
    assert_world_fidelity_oracle(observation)
    evidence = {
        "canonical_observation": observation,
        "durable_event_count": len(events),
        "failure_id": projected["failure_id"],
        "schema_id": "openzyme_world_fidelity_observation@1",
    }
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()
    )
    record_effect_ledger_snapshot(ExternalEffectLedger().snapshot())
