from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentAuthorization
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentCoordinator
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentError
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentPlan
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentStatus
from openzyme_hpc_ssh import WorkspaceRuntimeDeploymentScope
from openzyme_hpc_ssh import WorkspaceRuntimeDestinationState
from openzyme_hpc_ssh import WorkspaceRuntimeNativeQualification
from openzyme_hpc_ssh import OpenSshWorkspaceRuntimeDeploymentPort
from openzyme_hpc_ssh import workspace_runtime_source_bytes


DIGEST = "sha256:" + "a" * 64
OPERATOR = "operator.enzymedesign-owner"


def _plan(*, ready: bool = True) -> WorkspaceRuntimeDeploymentPlan:
    helper = workspace_runtime_source_bytes()
    authority = (
        {
            "installer_identity": "principal.grtresy.diannan",
            "privilege_mechanism": "direct-user-libexec-v1",
            "rollback_owner": "principal.grtresy.diannan",
        }
        if ready
        else {
            "installer_identity": None,
            "privilege_mechanism": None,
            "rollback_owner": None,
        }
    )
    return WorkspaceRuntimeDeploymentPlan.create(
        source_identity_digest=DIGEST,
        target_subject_digest=DIGEST,
        target_host_key_digest=DIGEST,
        helper_build_digest="sha256:" + hashlib.sha256(helper).hexdigest(),
        helper_version="1.0.0",
        target_login="grtresy",
        target_home="/home/grtresy",
        deployment_scope=(
            WorkspaceRuntimeDeploymentScope.TARGET_PRINCIPAL_USER_LIBEXEC
        ),
        destination_state=WorkspaceRuntimeDestinationState.MISSING,
        destination_pre_digest=None,
        **authority,
    )


def _authorization(plan: WorkspaceRuntimeDeploymentPlan):
    return WorkspaceRuntimeDeploymentAuthorization.create(
        authorization_id="authorization.workspace-runtime.diannan.1",
        plan_digest=plan.plan_digest,
        operator_id=OPERATOR,
        installer_identity=str(plan.installer_identity),
        privilege_mechanism=str(plan.privilege_mechanism),
        rollback_owner=str(plan.rollback_owner),
    )


class _Port:
    def __init__(self, plan: WorkspaceRuntimeDeploymentPlan) -> None:
        self.plan = plan
        self.calls: list[str] = []
        self.fail_qualification = False

    def observe_destination(self, path: str):
        self.calls.append("observe")
        return self.plan.destination_state.value, self.plan.destination_pre_digest

    def stage(self, *, path: str, content: bytes) -> str:
        self.calls.append("stage")
        return "sha256:" + hashlib.sha256(content).hexdigest()

    def install(self, plan: WorkspaceRuntimeDeploymentPlan) -> str:
        self.calls.append("install")
        return plan.helper_build_digest

    def qualify(self, plan: WorkspaceRuntimeDeploymentPlan):
        self.calls.append("qualify")
        return WorkspaceRuntimeNativeQualification(
            helper_build_digest=plan.helper_build_digest,
            root_policy_digest=DIGEST,
            principal_identity_digest=DIGEST,
            positive_probes=plan.positive_probes,
            negative_probes=plan.negative_probes,
            all_passed=not self.fail_qualification,
        )

    def rollback(self, plan, *, installed_digest: str) -> str:
        self.calls.append("rollback")
        return DIGEST


def test_blocked_plan_stops_before_deployment_port() -> None:
    plan = _plan(ready=False)
    port = _Port(plan)

    with pytest.raises(WorkspaceRuntimeDeploymentError) as captured:
        WorkspaceRuntimeDeploymentCoordinator(port).execute(
            plan=plan,
            authorization=None,
            expected_operator_id=OPERATOR,
            helper_bytes=workspace_runtime_source_bytes(),
        )

    assert plan.status is WorkspaceRuntimeDeploymentStatus.BLOCKED_DEPLOYMENT_AUTHORITY
    assert captured.value.error_code == "blocked_deployment_authority"
    assert port.calls == []


def test_exact_authority_installs_and_qualifies_without_fallback() -> None:
    plan = _plan()
    port = _Port(plan)

    receipt = WorkspaceRuntimeDeploymentCoordinator(port).execute(
        plan=plan,
        authorization=_authorization(plan),
        expected_operator_id=OPERATOR,
        helper_bytes=workspace_runtime_source_bytes(),
    )

    assert port.calls == ["observe", "stage", "install", "qualify"]
    assert receipt.installed_digest == plan.helper_build_digest
    assert receipt.fallback_performed is False


def test_native_failure_requests_exact_rollback_and_emits_no_receipt() -> None:
    plan = _plan()
    port = _Port(plan)
    port.fail_qualification = True

    with pytest.raises(WorkspaceRuntimeDeploymentError) as captured:
        WorkspaceRuntimeDeploymentCoordinator(port).execute(
            plan=plan,
            authorization=_authorization(plan),
            expected_operator_id=OPERATOR,
            helper_bytes=workspace_runtime_source_bytes(),
        )

    assert captured.value.error_code == "workspace_runtime_native_qualification_failed"
    assert port.calls[-1] == "rollback"


def test_unbound_destination_is_rejected_even_if_digest_is_recomputed() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="destination path is not exact"):
        replace(
            plan,
            destination_path="/tmp/openzyme-workspace-runtime",
            plan_digest="sha256:" + "0" * 64,
        )


def test_user_level_destination_is_exact_and_principal_bound() -> None:
    plan = _plan()

    assert plan.destination_path == (
        "/home/grtresy/.local/libexec/openzyme-workspace-runtime"
    )
    assert plan.file_owner == "grtresy"
    assert plan.deployment_scope is (
        WorkspaceRuntimeDeploymentScope.TARGET_PRINCIPAL_USER_LIBEXEC
    )
    assert WorkspaceRuntimeDeploymentPlan.from_dict(plan.to_dict()) == plan
    authorization = _authorization(plan)
    assert WorkspaceRuntimeDeploymentAuthorization.from_dict(
        authorization.to_dict()
    ) == authorization


def test_real_ssh_port_uses_exact_user_paths_without_sudo_or_path_lookup() -> None:
    plan = _plan()

    class _Remote:
        def __init__(self) -> None:
            self.scripts: list[str] = []

        def run_remote(self, script: str):
            self.scripts.append(script)
            if "if test -L \"$destination\"" in script:
                return 0, "missing\n", ""
            if "temporary=\"$staging.tmp.$$\"" in script:
                return 0, plan.helper_build_digest + "\n", ""
            if "mv -- \"$staging\" \"$destination\"" in script:
                return 0, plan.helper_build_digest + "\n", ""
            if "version_output=" in script:
                return (
                    0,
                    "\n".join(
                        (
                            f"BUILD={plan.helper_build_digest}",
                            f"POLICY={DIGEST}",
                            f"PRINCIPAL={DIGEST}",
                        )
                    ),
                    "",
                )
            raise AssertionError(script)

    remote = _Remote()
    port = OpenSshWorkspaceRuntimeDeploymentPort(remote)

    receipt = WorkspaceRuntimeDeploymentCoordinator(port).execute(
        plan=plan,
        authorization=_authorization(plan),
        expected_operator_id=OPERATOR,
        helper_bytes=workspace_runtime_source_bytes(),
    )

    combined = "\n".join(remote.scripts)
    assert receipt.installed_digest == plan.helper_build_digest
    assert plan.destination_path in combined
    assert plan.workspace_parent in combined
    assert "/usr/local/libexec" not in combined
    assert "sudo" not in combined
    assert "$HOME" not in combined
    assert "command -v" not in combined
