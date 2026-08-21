from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json

from openzyme_contracts import ToolInvocation
from openzyme_contracts.identity import JsonValue
from openzyme_hpc import HPC_WORKSPACE_TOOL_SPECS
from openzyme_hpc import HpcWorkspaceToolContext
from openzyme_hpc import build_hpc_workspace_tool_runtimes


DIGEST = "sha256:" + "a" * 64


@dataclass(slots=True)
class _Application:
    observed: tuple[str, HpcWorkspaceToolContext, Mapping[str, JsonValue]] | None = None

    def _accept(
        self,
        method: str,
        context: HpcWorkspaceToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]:
        self.observed = (method, context, arguments)
        return {
            "workspace_id": str(arguments.get("workspace_id") or "hpcws_new"),
            "state": "ready",
        }

    def request(self, context, arguments):
        return self._accept("request", context, arguments)

    def inspect(self, context, arguments):
        return self._accept("inspect", context, arguments)

    def verify(self, context, arguments):
        return self._accept("verify", context, arguments)

    def sync_source(self, context, arguments):
        return self._accept("sync_source", context, arguments)

    def fs_read(self, context, arguments):
        return self._accept("fs_read", context, arguments)

    def fs_list(self, context, arguments):
        return self._accept("fs_list", context, arguments)

    def fs_mutate(self, context, arguments):
        return self._accept("fs_mutate", context, arguments)

    def exec(self, context, arguments):
        return self._accept("exec", context, arguments)


@dataclass(slots=True)
class _InDoubtApplication(_Application):
    def exec(self, context, arguments):
        payload = dict(self._accept("exec", context, arguments))
        payload.update(
            effect_certainty="dispatch_in_doubt",
            mutation_applied=None,
            diagnostic_id="diagnostic-1",
        )
        return payload


def _invocation(tool_name: str, arguments: dict[str, JsonValue]) -> ToolInvocation:
    return ToolInvocation(
        call_id="call_1",
        tool_name=tool_name,
        arguments=arguments,
        session_id="session_1",
        agent_member_id="member_1",
        task_id="task_1",
        lane_id="lane_1",
        route_id="hpc-primary.workspace-runtime",
        affordance_snapshot_digest=DIGEST,
    )


def test_hpc_manifest_tool_contracts_are_closed_and_operation_scoped() -> None:
    assert [spec.tool_name for spec in HPC_WORKSPACE_TOOL_SPECS] == [
        "hpc.workspace.request",
        "hpc.workspace.inspect",
        "hpc.workspace.verify",
        "hpc.workspace.sync_source",
        "hpc.workspace.fs.read",
        "hpc.workspace.fs.list",
        "hpc.workspace.fs.mutate",
        "hpc.workspace.exec",
    ]
    assert all(spec.input_schema["additionalProperties"] is False for spec in HPC_WORKSPACE_TOOL_SPECS)
    assert {authority for spec in HPC_WORKSPACE_TOOL_SPECS for authority in spec.required_authorities} == {
        "hpc.workspace.fs.read",
        "hpc.workspace.fs.write",
        "hpc.workspace.inspect",
        "hpc.workspace.process.exec",
        "hpc.workspace.provision",
        "hpc.workspace.transfer.write",
    }
    public_contract = json.dumps(
        [spec.to_dict() for spec in HPC_WORKSPACE_TOOL_SPECS],
        sort_keys=True,
    )
    assert all(
        forbidden not in public_contract
        for forbidden in (
            "host_path",
            "artifact_catalog",
            "expected_outputs",
            "scheduler_job_id",
            "slurm_job_id",
            "login_alias",
            "remote_workspace_path",
            "remote_root",
        )
    )


def test_remote_exec_forwards_opaque_workspace_and_never_claims_formal_evidence() -> None:
    application = _Application()
    runtime = {
        item.tool_name: item
        for item in build_hpc_workspace_tool_runtimes(application)
    }["hpc.workspace.exec"]
    invocation = _invocation(
        "hpc.workspace.exec",
        {
            "workspace_id": "hpcws_1",
            "argv": ["hmmbuild", "model.hmm", "alignment.fasta"],
            "cwd": "analysis/hmmer",
            "timeout_seconds": 300,
            "idempotency_key": "exec_1",
        },
    )

    result = runtime.invoke(invocation)

    assert result.ok is True
    assert application.observed is not None
    method, context, arguments = application.observed
    assert method == "exec"
    assert context.call_id == "call_1"
    assert context.session_id == "session_1"
    assert context.agent_member_id == "member_1"
    assert context.route_id == "hpc-primary.workspace-runtime"
    assert arguments["workspace_id"] == "hpcws_1"
    assert result.payload["publication_created"] is False
    assert result.payload["scientific_evidence_created"] is False
    assert result.payload["task_finished"] is False
    assert result.payload["fallback_performed"] is False


def test_remote_exec_lost_response_never_redispatches_or_claims_no_effect() -> None:
    application = _InDoubtApplication()
    runtime = {
        item.tool_name: item
        for item in build_hpc_workspace_tool_runtimes(application)
    }["hpc.workspace.exec"]

    result = runtime.invoke(
        _invocation(
            "hpc.workspace.exec",
            {
                "workspace_id": "hpcws_1",
                "argv": ["hmmbuild", "model.hmm", "alignment.fasta"],
                "cwd": "analysis/hmmer",
                "timeout_seconds": 300,
                "idempotency_key": "exec_1",
            },
        )
    )

    assert result.ok is False
    assert result.status == "dispatch_in_doubt"
    assert result.error_code == "remote_workspace_dispatch_in_doubt"
    assert result.payload["mutation_applied"] is None
    assert result.payload["fallback_performed"] is False
    assert application.observed is not None
