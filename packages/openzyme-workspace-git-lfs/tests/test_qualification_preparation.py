from pathlib import Path
from types import SimpleNamespace

from openzyme_workspace_git_lfs import LocalIsolatedGitLfsPreparationExecutor


class _Commands:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        self.calls.append(argv)
        return 0, "ok", ""


def test_local_git_lfs_preparation_is_isolated_and_cleanup_is_owned(
    tmp_path: Path,
) -> None:
    commands = _Commands()
    root = tmp_path / "git-lfs"
    executor = LocalIsolatedGitLfsPreparationExecutor(
        repository_root=root,
        command_port=commands,
    )
    action = SimpleNamespace(
        action_id="prepare.batch-1.git-primary",
        owner_component_id="openzyme.workspace.git.lfs",
        effect_id="git-lfs.local-isolated-repository.create",
        credential_locator_id=None,
        input_binding_digest="sha256:" + "3" * 64,
    )

    result = executor(
        plan=SimpleNamespace(preparation_plan_digest="sha256:" + "1" * 64),
        authorization=SimpleNamespace(authorization_digest="sha256:" + "2" * 64),
        action=action,
        occurrence_id="occurrence.git-preparation",
        request_digest="sha256:" + "4" * 64,
        credential_material=None,
    )

    assert [call[:2] for call in commands.calls] == [
        ("git", "init"),
        ("git", "--git-dir"),
    ]
    assert {item.field_id for item in result.safe_identity_fields} == {
        "local_repository_endpoint",
        "local_lfs_endpoint_identity",
        "repository_policy_digest",
        "local_process_scope_digest",
    }
    assert str(root) not in str(result.to_dict())
    assert result.observation.credential_material_accessed is False
    executor.cleanup("occurrence.git-preparation")
    assert not (root / "occurrence.git-preparation").exists()
