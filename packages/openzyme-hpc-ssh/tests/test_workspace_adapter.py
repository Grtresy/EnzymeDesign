from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import base64
import json

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceFilesystemMutation
from openzyme_contracts import WorkspaceFilesystemMutationKind
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import WorkspaceTransferDirection
from openzyme_contracts import WorkspaceTransferRequest
from openzyme_hpc_ssh import PrivateRemoteWorkspaceLocator
from openzyme_hpc_ssh import PrivateSshCredentialMaterial
from openzyme_hpc_ssh import RemoteWorkspaceTransportOutcome
from openzyme_hpc_ssh import SSH_WORKSPACE_PROVIDER_ID
from openzyme_hpc_ssh import SshWorkspaceAdapter
from openzyme_hpc_ssh import SshCommandError
from openzyme_hpc_ssh import SshCommandResult
from openzyme_hpc_ssh import SshJsonCommandTransport


DIGEST = "sha256:" + "a" * 64


def _binding(*, generation: int = 2) -> WorkspaceRuntimeBinding:
    return WorkspaceRuntimeBinding(
        workspace_id="hpc_workspace_1",
        workspace_kind=WorkspaceKind.EXECUTOR_REMOTE,
        session_id="session_1",
        owner_member_id="member_1",
        generation=generation,
        state_version=3,
        root_identity_digest=DIGEST,
        provider_id=SSH_WORKSPACE_PROVIDER_ID,
        target_id="hpc:primary",
        target_qualification_digest=DIGEST,
    )


def _locator() -> PrivateRemoteWorkspaceLocator:
    return PrivateRemoteWorkspaceLocator(
        workspace_id="hpc_workspace_1",
        session_id="session_1",
        owner_member_id="member_1",
        generation=2,
        state_version=3,
        target_id="hpc:primary",
        target_qualification_digest=DIGEST,
        root_identity_digest=DIGEST,
        remote_root="/srv/openzyme/workspaces/member-1",
        credential_claim_id="claim_1",
    )


@dataclass
class _Resolver:
    locator: PrivateRemoteWorkspaceLocator | None

    def resolve(self, _: WorkspaceRuntimeBinding) -> PrivateRemoteWorkspaceLocator | None:
        return self.locator


class _Transport:
    def __init__(self) -> None:
        self.dispatch_calls: list[dict[str, object]] = []
        self.reconcile_calls: list[dict[str, object]] = []
        self.dispatch_outcome: RemoteWorkspaceTransportOutcome | None = None
        self.reconcile_outcome: RemoteWorkspaceTransportOutcome | None = None

    def dispatch(self, **values: object) -> RemoteWorkspaceTransportOutcome:
        self.dispatch_calls.append(values)
        assert self.dispatch_outcome is not None
        return self.dispatch_outcome

    def reconcile(self, **values: object) -> RemoteWorkspaceTransportOutcome:
        self.reconcile_calls.append(values)
        assert self.reconcile_outcome is not None
        return self.reconcile_outcome


@dataclass
class _CredentialResolver:
    material: PrivateSshCredentialMaterial | None

    def resolve(self, _: str) -> PrivateSshCredentialMaterial | None:
        return self.material


class _CommandExecutor:
    def __init__(self, result: SshCommandResult | SshCommandError) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def execute(self, **values: object) -> SshCommandResult:
        self.calls.append(values)
        if isinstance(self.result, SshCommandError):
            raise self.result
        return self.result


def _exec() -> WorkspaceExecRequest:
    return WorkspaceExecRequest(
        operation_id="operation_1",
        binding=_binding(),
        argv=("hmmbuild", "model.hmm", "alignment.fasta"),
        cwd="analysis/hmmer",
        timeout_seconds=300,
        max_output_bytes=65_536,
        idempotency_key="hmmer_build_1",
        authority_lease_id="lease_1",
        authority_generation=2,
        authority_fence=4,
        process_epoch=5,
    )


def test_exec_uses_private_locator_and_preserves_bounded_argv_without_scheduler() -> None:
    request = _exec()
    transport = _Transport()
    transport.dispatch_outcome = RemoteWorkspaceTransportOutcome(
        operation_id=request.operation_id,
        request_digest=request.intent_digest,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        result_payload=b'{"exit_code":0}',
    )
    adapter = SshWorkspaceAdapter(_Resolver(_locator()), transport)

    receipt = adapter.execute(request)

    assert receipt.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    call = transport.dispatch_calls[0]
    assert call["operation_kind"] == "ssh.exec"
    payload = call["payload"]
    assert isinstance(payload, dict)
    assert payload["argv"] == list(request.argv)
    assert "scheduler" not in str(call).lower()
    assert "sbatch" not in str(call).lower()


def test_lost_exec_response_reconciles_same_occurrence_without_redispatch() -> None:
    request = _exec()
    transport = _Transport()
    transport.dispatch_outcome = RemoteWorkspaceTransportOutcome(
        operation_id=request.operation_id,
        request_digest=request.intent_digest,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        mutation_applied=None,
        diagnostic_id="diagnostic_1",
    )
    transport.reconcile_outcome = RemoteWorkspaceTransportOutcome(
        operation_id=request.operation_id,
        request_digest=request.intent_digest,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        result_payload=b'{"exit_code":0}',
    )
    adapter = SshWorkspaceAdapter(_Resolver(_locator()), transport)

    uncertain = adapter.execute(request)
    settled = adapter.reconcile(request)

    assert uncertain.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert settled.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert len(transport.dispatch_calls) == 1
    assert transport.reconcile_calls == [
        {
            "locator": _locator(),
            "operation_id": request.operation_id,
            "request_digest": request.intent_digest,
        }
    ]


def test_stale_workspace_generation_fails_before_transport() -> None:
    request = replace(_exec(), binding=_binding(generation=3))
    transport = _Transport()
    adapter = SshWorkspaceAdapter(_Resolver(_locator()), transport)

    with pytest.raises(WorkspacePortError) as caught:
        adapter.execute(request)

    assert caught.value.error_code == "remote_workspace_binding_stale"
    assert caught.value.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert transport.dispatch_calls == []


def test_filesystem_and_transfer_requests_remain_root_relative_and_opaque() -> None:
    with pytest.raises(ValueError, match="inside the workspace root"):
        WorkspaceFilesystemMutation(
            operation_id="operation_fs",
            binding=_binding(),
            operation=WorkspaceFilesystemMutationKind.REMOVE,
            path="../other-owner/file.txt",
            idempotency_key="remove_1",
            authority_lease_id="lease_1",
            authority_generation=2,
            authority_fence=4,
        )
    with pytest.raises(ValueError, match="opaque identifier"):
        WorkspaceTransferRequest(
            operation_id="operation_transfer",
            binding=_binding(),
            direction=WorkspaceTransferDirection.UPLOAD,
            path="results/data.bin",
            transfer_ref="/tmp/data.bin",
            transfer_manifest_digest=DIGEST,
            max_bytes=1024,
            timeout_seconds=60,
            idempotency_key="upload_1",
            authority_lease_id="lease_1",
            authority_generation=2,
            authority_fence=4,
        )


def test_command_transport_uses_exact_ssh_argv_and_closed_private_envelope() -> None:
    response = {
        "schema_version": "ssh_workspace_private_response@1",
        "operation_id": "operation_1",
        "request_digest": DIGEST,
        "effect_certainty": "terminal_known",
        "mutation_applied": True,
        "result_base64": base64.b64encode(b'{"exit_code":0}').decode("ascii"),
        "diagnostic_id": None,
    }
    executor = _CommandExecutor(
        SshCommandResult(
            return_code=0,
            stdout=json.dumps(response).encode(),
            stderr=b"",
        )
    )
    transport = SshJsonCommandTransport(
        credential_resolver=_CredentialResolver(
            PrivateSshCredentialMaterial(
                credential_claim_id="claim_1",
                target_alias="hpc-primary",
                identity_file="/run/openzyme/credentials/claim_1",
            )
        ),
        executor=executor,
    )

    outcome = transport.dispatch(
        locator=_locator(),
        operation_id="operation_1",
        request_digest=DIGEST,
        operation_kind="ssh.exec",
        payload={"argv": ["hmmbuild", "model.hmm", "alignment.fasta"]},
        timeout_seconds=300,
        max_output_bytes=65_536,
    )

    assert outcome.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    call = executor.calls[0]
    assert call["argv"] == (
        "/usr/bin/ssh",
        "-T",
        "-oBatchMode=yes",
        "-oIdentitiesOnly=yes",
        "-i",
        "/run/openzyme/credentials/claim_1",
        "hpc-primary",
        "/usr/local/libexec/openzyme-workspace-runtime",
        "dispatch",
    )
    envelope = json.loads(call["stdin"])
    assert envelope["remote_root"] == _locator().remote_root
    assert envelope["payload"]["argv"][0] == "hmmbuild"
    assert "sbatch" not in str(call).lower()


def test_command_transport_preserves_timeout_uncertainty() -> None:
    executor = _CommandExecutor(
        SshCommandError(
            "response lost",
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            diagnostic_id="diagnostic_1",
        )
    )
    transport = SshJsonCommandTransport(
        credential_resolver=_CredentialResolver(
            PrivateSshCredentialMaterial(
                credential_claim_id="claim_1",
                target_alias="hpc-primary",
                identity_file="/run/openzyme/credentials/claim_1",
            )
        ),
        executor=executor,
    )

    outcome = transport.dispatch(
        locator=_locator(),
        operation_id="operation_1",
        request_digest=DIGEST,
        operation_kind="rsync.transfer",
        payload={"transfer_ref": "transfer_1"},
        timeout_seconds=60,
        max_output_bytes=65_536,
    )

    assert outcome.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert outcome.mutation_applied is None
    assert outcome.result_payload == b""
