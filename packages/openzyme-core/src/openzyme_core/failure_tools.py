from __future__ import annotations

import hashlib
import json

from openzyme_domain import FailureHypothesis
from openzyme_domain import FailureHypothesisConfidence
from openzyme_domain import utc_now_iso
from openzyme_runtime import sanitize_public_diagnostic_text

from .failure_repositories import project_failure_observation
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hypothesis_id(
    *,
    session_id: str,
    agent_id: str,
    idempotency_key: str,
) -> str:
    digest = _digest(
        json.dumps(
            {
                "session_id": session_id,
                "agent_id": agent_id,
                "idempotency_key": idempotency_key,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return "failure_hypothesis_" + digest.removeprefix("sha256:")[:20]


def _agent_id(context: SessionRuntimeContext) -> str:
    agent_id = str(context.agent_id or "")
    if not agent_id.startswith("agent:"):
        raise ValueError(
            "failure hypotheses require the canonical identity of a live agent"
        )
    if (
        context.repositories.agents.get(
            context.snapshot.session.session_id,
            agent_id,
        )
        is None
    ):
        raise ValueError(
            "failure hypotheses require a canonical agent in the current session"
        )
    return agent_id


def _success(
    invocation: ToolInvocation,
    *,
    payload: dict[str, object],
    status: str,
    summary: str,
) -> ToolResult:
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=True,
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=status,
        summary=summary,
        details=payload,
    )


def register_failure_tools(registry: ToolRegistry) -> None:
    def get_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        failure_id = str(invocation.arguments["failure_id"])
        failure = context.repositories.failure_observations.get(failure_id)
        if failure is None or failure.session_id != context.snapshot.session.session_id:
            raise ValueError(
                "failure_id does not resolve to a failure in the current session"
            )
        payload = project_failure_observation(context.repositories, failure)
        return _success(
            invocation,
            payload=payload,
            status="failure_observation_projected",
            summary=f"Projected failure observation {failure_id}.",
        )

    def hypothesis_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        session_id = context.snapshot.session.session_id
        agent_id = _agent_id(context)
        failure_id = str(arguments["failure_id"])
        failure = context.repositories.failure_observations.get(failure_id)
        if failure is None or failure.session_id != session_id:
            raise ValueError(
                "failure_id does not resolve to a failure in the current session"
            )
        hypothesis = sanitize_public_diagnostic_text(
            str(arguments["hypothesis"])
        ).strip()
        if not hypothesis:
            raise ValueError("hypothesis must be non-empty")
        confidence = FailureHypothesisConfidence(str(arguments["confidence"]))
        evidence_refs = tuple(
            sanitize_public_diagnostic_text(str(value)).strip()
            for value in arguments.get("evidence_refs", ())
        )
        idempotency_key = str(arguments["idempotency_key"]).strip()
        if not idempotency_key:
            raise ValueError("idempotency_key must be non-empty")
        record = FailureHypothesis(
            hypothesis_id=_hypothesis_id(
                session_id=session_id,
                agent_id=agent_id,
                idempotency_key=idempotency_key,
            ),
            failure_id=failure_id,
            session_id=session_id,
            agent_id=agent_id,
            hypothesis=hypothesis,
            confidence=confidence,
            evidence_refs=evidence_refs,
            idempotency_digest=_digest(idempotency_key),
            created_at=utc_now_iso(),
        )
        saved = context.repositories.failure_hypotheses.add(record)
        context.emit(
            "failure.hypothesis.recorded",
            {
                "hypothesis_id": saved.hypothesis_id,
                "failure_id": saved.failure_id,
                "agent_id": saved.agent_id,
                "confidence": saved.confidence.value,
                "evidence_refs": list(saved.evidence_refs),
            },
        )
        return _success(
            invocation,
            payload=saved.to_dict(),
            status="failure_hypothesis_recorded",
            summary=(
                f"Recorded agent-attributed hypothesis {saved.hypothesis_id} "
                f"for failure {saved.failure_id}."
            ),
        )

    registry.register("failure.get", get_handler)
    registry.register("failure.hypothesis.record", hypothesis_handler)


__all__ = ["register_failure_tools"]
