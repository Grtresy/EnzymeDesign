import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from enzymedesign_distribution.qualification_operator_state import (
    ProtectedQualificationCredentialBundleResolver,
)
from enzymedesign_distribution.qualification_operator_state import (
    QUALIFICATION_CREDENTIAL_BUNDLE_SCHEMA,
)
from enzymedesign_distribution.qualification_operator_state import (
    QUALIFICATION_OPERATOR_LAYOUT_SCHEMA,
)
from enzymedesign_distribution.qualification_operator_state import (
    QualificationOperatorStateLayout,
)
from enzymedesign_distribution.qualification_preparation_runtime import (
    EnzymeDesignHpcIdentityPreparationExecutor,
)
from enzymedesign_distribution.qualification_preparation_runtime import (
    build_enzymedesign_identity_preparation_backend_factory,
)
from enzymedesign_distribution.qualification_preparation_runtime import (
    preflight_enzymedesign_identity_preparation_credentials,
)
from openzyme_hpc import HpcQualificationIdentityObservation
from openzyme_contracts import ExternalQualificationError


LLM_LOCATOR = "credential.llm.micuapi.qualification"
SECRET_CANARY = "sk-private-qualification-canary-123456789"


def _write_private(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def _layout(tmp_path: Path) -> QualificationOperatorStateLayout:
    root = tmp_path / "operator-state"
    root.mkdir(mode=0o700)
    _write_private(
        root / "layout.json",
        {
            "schema_version": QUALIFICATION_OPERATOR_LAYOUT_SCHEMA,
            "layout_id": "qualification.operator-state.primary",
        },
    )
    return QualificationOperatorStateLayout.open(root)


def test_layout_exposes_only_logical_safe_identity(tmp_path: Path) -> None:
    layout = _layout(tmp_path)

    assert str(layout.root) not in repr(layout)
    assert layout.safe_identity() == {
        "layout_id": "qualification.operator-state.primary",
        "policy_digest": layout.policy_digest,
        "ledger_id": "qualification.ledger.protected.operator-state-root.sqlite",
        "private_evidence_root_id": (
            "qualification.evidence.protected.operator-state-root"
        ),
    }
    assert layout.policy_digest.startswith("sha256:")


def test_layout_bootstrap_creates_only_owner_private_skeleton(tmp_path: Path) -> None:
    root = tmp_path / "operator-state"

    layout = QualificationOperatorStateLayout.bootstrap(root)
    repeated = QualificationOperatorStateLayout.bootstrap(root)

    assert repeated == layout
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / "layout.json").stat().st_mode & 0o777 == 0o600
    assert not layout.credential_bundle_path.exists()
    assert not layout.ledger_path.exists()
    assert {item.name for item in root.iterdir()} == {"layout.json"}


def test_preparation_authorization_writer_ignores_permissive_umask(
    tmp_path: Path,
) -> None:
    root = tmp_path / "authorization-root"
    root.mkdir(mode=0o700)
    output = root / "authorization.json"
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts/create-external-identity-preparation-authorization.py"
    environment = dict(os.environ)
    environment["OPENZYME_ALLOW_LIVE"] = "0"

    subprocess.run(
        (
            sys.executable,
            str(script),
            str(output),
            "--authorization-id",
            "authorization.preparation.permissions-test",
            "--preparation-plan-digest",
            "sha256:" + "1" * 64,
            "--batch-id",
            "batch-1",
            "--operator-id",
            "operator.enzymedesign-owner",
            "--authorized-at",
            "2026-08-23T18:30:00+08:00",
        ),
        cwd=repo_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert output.stat().st_mode & 0o777 == 0o600


def test_layout_rejects_group_readable_or_symlinked_state(tmp_path: Path) -> None:
    root = tmp_path / "unsafe-state"
    root.mkdir(mode=0o750)
    root.chmod(0o750)
    with pytest.raises(ExternalQualificationError) as captured:
        QualificationOperatorStateLayout.open(root)
    assert captured.value.error_code == (
        "qualification_operator_state_permissions_unsafe"
    )

    target = tmp_path / "target-state"
    target.mkdir(mode=0o700)
    link = tmp_path / "linked-state"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ExternalQualificationError) as linked:
        QualificationOperatorStateLayout.open(link)
    assert linked.value.error_code == "qualification_operator_state_symlink_forbidden"


def test_resolver_reads_only_exact_locator_and_redacts_material(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_private(
        layout.credential_bundle_path,
        {
            "schema_version": QUALIFICATION_CREDENTIAL_BUNDLE_SCHEMA,
            "bundle_id": "qualification.credentials.primary",
            "locators": {
                LLM_LOCATOR: {
                    "material_kind": "bearer-token",
                    "locator_version": "v1",
                    "fields": {"token": SECRET_CANARY},
                }
            },
        },
    )
    resolver = ProtectedQualificationCredentialBundleResolver(
        layout=layout,
        allowed_locator_ids=(LLM_LOCATOR,),
    )

    material = resolver.resolve(locator_id=LLM_LOCATOR)

    assert material.field_value("token") == SECRET_CANARY
    assert SECRET_CANARY not in repr(material)
    assert SECRET_CANARY not in str(material)
    assert str(layout.root) not in repr(material)


def test_resolver_rejects_unplanned_locator_before_bundle_access(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    assert not layout.credential_bundle_path.exists()
    resolver = ProtectedQualificationCredentialBundleResolver(
        layout=layout,
        allowed_locator_ids=(LLM_LOCATOR,),
    )

    with pytest.raises(ExternalQualificationError) as captured:
        resolver.resolve(locator_id="credential.tavily.qualification")

    assert captured.value.error_code == "qualification_credential_locator_mismatch"
    assert not layout.credential_bundle_path.exists()


def test_resolver_rejects_unsafe_bundle_mode_without_reading_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(tmp_path)
    _write_private(
        layout.credential_bundle_path,
        {
            "schema_version": QUALIFICATION_CREDENTIAL_BUNDLE_SCHEMA,
            "bundle_id": "qualification.credentials.primary",
            "locators": {},
        },
    )
    layout.credential_bundle_path.chmod(0o640)
    reads = 0
    original = Path.read_text

    def counted_read(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal reads
        if path == layout.credential_bundle_path:
            reads += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read)
    resolver = ProtectedQualificationCredentialBundleResolver(
        layout=layout,
        allowed_locator_ids=(LLM_LOCATOR,),
    )

    with pytest.raises(ExternalQualificationError) as captured:
        resolver.resolve(locator_id=LLM_LOCATOR)

    assert captured.value.error_code == (
        "qualification_operator_state_permissions_unsafe"
    )
    assert reads == 0
    os.chmod(layout.credential_bundle_path, 0o600)


def test_concrete_preparation_runtime_assembly_is_read_only(tmp_path: Path) -> None:
    layout = _layout(tmp_path)

    factory = build_enzymedesign_identity_preparation_backend_factory(
        layout=layout,
        allowed_locator_ids=(
            LLM_LOCATOR,
            "credential.tavily.qualification",
            "credential.hpc.diannan.qualification",
        ),
    )

    assert factory is not None
    assert not layout.credential_bundle_path.exists()
    assert not layout.ledger_path.exists()
    assert not (layout.root / "git-lfs").exists()
    assert not (layout.root / "hpc-qualification").exists()


def test_credential_preflight_covers_every_exact_locator_before_mutation(
    tmp_path: Path,
) -> None:
    from enzymedesign_distribution import ExternalQualificationBatch
    from enzymedesign_distribution import OPTIONAL_PROFILES
    from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
    from enzymedesign_distribution import build_external_identity_gaps
    from enzymedesign_distribution import build_external_identity_preparation_plan
    from enzymedesign_distribution import build_external_identity_resolution_decisions
    from enzymedesign_distribution import discover_external_subject_identities
    from enzymedesign_distribution import load_operator_identity_resolution_selections
    from enzymedesign_distribution import load_safe_identity_snapshot

    repo_root = Path(__file__).resolve().parents[3]
    operator_root = (
        repo_root
        / "openspec/changes/qualify-enzymedesign-external-capability-routes/operator"
    )
    snapshot = load_safe_identity_snapshot(
        operator_root / "safe-identity-snapshot-20260822.json"
    )
    selections = load_operator_identity_resolution_selections(
        operator_root / "approved-identity-resolution-selections-20260822.json"
    )
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.preflight",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    gaps = build_external_identity_gaps(discovery)
    plan = build_external_identity_preparation_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=gaps,
        decisions=build_external_identity_resolution_decisions(
            gaps=gaps,
            snapshot=snapshot,
            selection_set=selections,
        ),
        selection_set=selections,
        batch=ExternalQualificationBatch.BATCH_1,
    )
    layout = _layout(tmp_path)
    _write_private(
        layout.credential_bundle_path,
        {
            "schema_version": QUALIFICATION_CREDENTIAL_BUNDLE_SCHEMA,
            "bundle_id": "qualification.credentials.primary",
            "locators": {
                "credential.llm.micuapi.qualification": {
                    "material_kind": "bearer-token",
                    "locator_version": "v1",
                    "fields": {
                        "token": SECRET_CANARY,
                        "account_locator_id": "account.llm.qualification",
                        "scope_id": "scope.llm.qualification",
                    },
                },
                "credential.tavily.qualification": {
                    "material_kind": "bearer-token",
                    "locator_version": "v1",
                    "fields": {
                        "token": SECRET_CANARY,
                        "account_locator_id": "account.tavily.qualification",
                        "scope_id": "scope.tavily.qualification",
                    },
                },
                "credential.hpc.diannan.qualification": {
                    "material_kind": "openssh-identity",
                    "locator_version": "v1",
                    "fields": {
                        "ssh_host": "hpc.invalid",
                        "ssh_port": "22222",
                        "ssh_user": "qualification-user",
                        "identity_file": "/private/id",
                        "known_hosts_file": "/private/known-hosts",
                        "credential_provider_id": "provider.file",
                        "authenticator_id": "auth.openssh",
                        "login_alias": "diannan-qualification",
                        "workspace_root": "/qualification/workspaces",
                        "sidecar_root": "/qualification/sidecars",
                        "isolation_command": "/qualification/isolate",
                        "slurm_policy_id": "slurm.3090.qualification",
                    },
                },
            },
        },
    )
    resolver = ProtectedQualificationCredentialBundleResolver(
        layout=layout,
        allowed_locator_ids=plan.credential_locator_ids,
    )

    preloaded = preflight_enzymedesign_identity_preparation_credentials(
        plan=plan,
        resolver=resolver,
    )

    assert all(
        preloaded.resolve(locator_id=locator_id) is not None
        for locator_id in plan.credential_locator_ids
    )
    assert not layout.ledger_path.exists()
    assert not (layout.root / "git-lfs").exists()


class _HpcMaterial:
    locator_id = "credential.hpc.diannan.qualification"
    locator_version = "v1"
    material_kind = "openssh-identity"

    def field_value(self, field_name: str) -> str:
        return {
            "ssh_port": "22222",
            "credential_provider_id": "qualification-file-provider-v1",
            "authenticator_id": "openssh-identities-only-v1",
            "login_alias": "diannan-qualification",
            "workspace_root": "/data/openzyme/qualification/workspaces",
            "sidecar_root": "/data/openzyme/qualification/sidecars",
            "isolation_command": "/usr/local/libexec/openzyme-workspace-isolation",
            "slurm_policy_id": "partition-3090-no-account-override",
        }[field_name]


class _HpcObservation:
    def observe(self, **_kwargs: object) -> HpcQualificationIdentityObservation:
        return HpcQualificationIdentityObservation(
            host_alias="Diannan",
            ssh_port=22222,
            partition="3090",
            environment_digest="sha256:" + "5" * 64,
            inventory_generation_digest="sha256:" + "6" * 64,
            software_versions=(
                ("software.fpocket", "4.2.3"),
                ("software.hmmer", "3.4"),
                ("software.vina", "1.2.7"),
            ),
        )


def test_hpc_identity_preparation_writes_only_qualification_config(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "hpc-qualification" / "config.json"
    executor = EnzymeDesignHpcIdentityPreparationExecutor(
        private_config_path=config_path,
        observation_port=_HpcObservation(),
    )
    result = executor(
        plan=SimpleNamespace(
            preparation_plan_digest="sha256:" + "1" * 64,
            batch_id="batch-1",
        ),
        authorization=SimpleNamespace(authorization_digest="sha256:" + "2" * 64),
        action=SimpleNamespace(
            action_id="prepare.batch-1.hpc-primary",
            owner_component_id="openzyme.hpc",
            effect_id="hpc.executor-workspace-v2.identity-resolve",
            credential_locator_id="credential.hpc.diannan.qualification",
            input_binding_digest="sha256:" + "3" * 64,
        ),
        occurrence_id="occurrence.hpc-identity-preparation",
        request_digest="sha256:" + "4" * 64,
        credential_material=_HpcMaterial(),
    )

    assert config_path.stat().st_mode & 0o777 == 0o600
    payload = config_path.read_text(encoding="utf-8")
    assert '"configuration_mode":"qualification-only"' in payload
    assert '"ssh_port":22222' in payload
    assert '"activated":false' in payload
    assert '"scheduler_submit_enabled":false' in payload
    assert {item.field_id for item in result.safe_identity_fields} == {
        "authenticator_identity",
        "credential_locator_id",
        "credential_provider_identity",
        "executor_workspace_v2_profile",
        "fpocket_software_fact",
        "hmmer_software_fact",
        "hpc_inventory_generation_digest",
        "inventory_generation_digest",
        "slurm_account_or_qos_policy",
        "vina_software_fact",
    }
