from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_contracts import SafeIdentityField
from openzyme_contracts import ExternalQualificationError
from openzyme_process_podman.qualification_images import (
    PodmanQualificationImagePreparationExecutor,
)
from openzyme_process_podman.qualification_images import (
    load_qualification_image_manifest,
)


def test_repository_owned_qualification_images_bind_exact_sources_and_lock() -> None:
    manifest = load_qualification_image_manifest()

    assert tuple(item.image_group for item in manifest.recipes) == (
        "base",
        "docking",
        "hmmer",
    )
    assert manifest.manifest_digest.startswith("sha256:")
    assert {source.commit for item in manifest.recipes for source in item.sources} == {
        "9acd8b6758a0ca5d21db6d167e0277484341929b",
        "8eb40404f4f45608acb3b01427587ac049f27c1f",
        "4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066",
    }
    for recipe in manifest.recipes:
        assert recipe.base_image_ref == (
            "docker.io/library/python@sha256:"
            "356b0d18f9385f4bdcc673af60e1e64c9d1504952e4ec36ee32044c722a6bc4e"
        )
        assert recipe.output_image_ref.startswith("localhost/openzyme-qualification-")
        assert recipe.uv_lock_digest == (
            "sha256:08ea390c480ef23d2f79282042849a989577ee7ff5de9f996a5ff76b60ae1c45"
        )
        assert recipe.recipe_digest.startswith("sha256:")


def test_build_commands_are_exact_and_do_not_pull_mutable_base() -> None:
    manifest = load_qualification_image_manifest()

    for recipe in manifest.recipes:
        argv = recipe.build_argv()
        assert argv[:3] == ("podman", "build", "--pull=never")
        assert f"BASE_IMAGE_REF={recipe.base_image_ref}" in argv
        assert argv[-1] == "."
        assert recipe.output_image_ref in argv
        assert all(
            any(argument.endswith(f"={source.commit}") for argument in argv)
            for source in recipe.sources
        )


class _Commands:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path | None]] = []

    def run(
        self, argv: tuple[str, ...], *, working_directory: Path | None = None
    ) -> tuple[int, str, str]:
        self.calls.append((argv, working_directory))
        if argv[:3] == ("podman", "image", "exists"):
            return (0, "", "") if "@sha256:" in argv[-1] else (1, "", "")
        if argv[:3] == ("podman", "image", "inspect"):
            return 0, "sha256:" + "a" * 64 + "\n", ""
        return 0, "built", ""


def test_docking_preparation_builds_once_and_projects_all_image_facts() -> None:
    commands = _Commands()
    executor = PodmanQualificationImagePreparationExecutor(command_port=commands)
    action = SimpleNamespace(
        action_id="prepare.batch-1.image-docking",
        owner_component_id="openzyme.process.podman",
        effect_id="podman.qualification-image.resolve.docking",
        credential_locator_id=None,
        input_binding_digest="sha256:" + "3" * 64,
        safe_input_fields=(SafeIdentityField("image_group", "docking"),),
    )
    result = executor(
        plan=SimpleNamespace(preparation_plan_digest="sha256:" + "1" * 64),
        authorization=SimpleNamespace(authorization_digest="sha256:" + "2" * 64),
        action=action,
        occurrence_id="occurrence.docking-image-preparation",
        request_digest="sha256:" + "4" * 64,
        credential_material=None,
    )

    assert len(commands.calls) == 4
    assert commands.calls[0][0][:3] == ("podman", "image", "exists")
    assert commands.calls[1][0][:3] == ("podman", "image", "exists")
    assert commands.calls[2][0][:3] == ("podman", "build", "--pull=never")
    assert commands.calls[2][1] is not None
    assert {item.field_id for item in result.safe_identity_fields} == {
        "fpocket_image_digest",
        "fpocket_version",
        "meeko_version",
        "openbabel_version",
        "preprocess_image_digest",
        "rdkit_version",
        "vina_image_digest",
        "vina_version",
    }
    assert result.observation.external_effect_performed is True


def test_preparation_refuses_to_overwrite_an_existing_output_image() -> None:
    class _ExistingCommands(_Commands):
        def run(
            self, argv: tuple[str, ...], *, working_directory: Path | None = None
        ) -> tuple[int, str, str]:
            self.calls.append((argv, working_directory))
            return 0, "", ""

    commands = _ExistingCommands()
    executor = PodmanQualificationImagePreparationExecutor(command_port=commands)
    action = SimpleNamespace(
        action_id="prepare.batch-1.image-base",
        owner_component_id="openzyme.process.podman",
        effect_id="podman.qualification-image.resolve.base",
        credential_locator_id=None,
        input_binding_digest="sha256:" + "3" * 64,
        safe_input_fields=(SafeIdentityField("image_group", "base"),),
    )

    with pytest.raises(ExternalQualificationError) as captured:
        executor(
            plan=SimpleNamespace(preparation_plan_digest="sha256:" + "1" * 64),
            authorization=SimpleNamespace(authorization_digest="sha256:" + "2" * 64),
            action=action,
            occurrence_id="occurrence.base-image-preparation",
            request_digest="sha256:" + "4" * 64,
            credential_material=None,
        )

    assert captured.value.error_code == "qualification_image_output_already_exists"
    assert len(commands.calls) == 1


def test_build_failure_preserves_bounded_private_diagnostic_without_retry() -> None:
    class _FailingCommands(_Commands):
        def run(
            self, argv: tuple[str, ...], *, working_directory: Path | None = None
        ) -> tuple[int, str, str]:
            self.calls.append((argv, working_directory))
            if argv[:3] == ("podman", "image", "exists"):
                return (0, "", "") if "@sha256:" in argv[-1] else (1, "", "")
            return 23, "x" * 9000, "apt dependency conflict"

    commands = _FailingCommands()
    executor = PodmanQualificationImagePreparationExecutor(command_port=commands)
    action = SimpleNamespace(
        action_id="prepare.batch-1.image-base",
        owner_component_id="openzyme.process.podman",
        effect_id="podman.qualification-image.resolve.base",
        credential_locator_id=None,
        input_binding_digest="sha256:" + "3" * 64,
        safe_input_fields=(SafeIdentityField("image_group", "base"),),
    )

    with pytest.raises(ExternalQualificationError) as captured:
        executor(
            plan=SimpleNamespace(preparation_plan_digest="sha256:" + "1" * 64),
            authorization=SimpleNamespace(authorization_digest="sha256:" + "2" * 64),
            action=action,
            occurrence_id="occurrence.base-image-preparation",
            request_digest="sha256:" + "4" * 64,
            credential_material=None,
        )

    failure = captured.value
    assert failure.error_code == "qualification_image_build_failed"
    assert failure.diagnostic_id == (
        "diagnostic.occurrence.base-image-preparation.qualification-image-build"
    )
    assert failure.mutation_applied is True
    assert failure.fallback_performed is False
    assert failure.returncode == 23
    assert len(failure.bounded_stdout) < 9000
    assert failure.stdout_truncated is True
    assert failure.bounded_stderr == "apt dependency conflict"
    assert failure.stderr_truncated is False
    assert len(commands.calls) == 3


def test_missing_base_is_pulled_by_digest_then_build_remains_pull_never() -> None:
    class _PullingCommands(_Commands):
        def __init__(self) -> None:
            super().__init__()
            self.base_available = False

        def run(
            self, argv: tuple[str, ...], *, working_directory: Path | None = None
        ) -> tuple[int, str, str]:
            self.calls.append((argv, working_directory))
            if argv[:3] == ("podman", "image", "exists"):
                if "@sha256:" not in argv[-1]:
                    return 1, "", ""
                return (0, "", "") if self.base_available else (1, "", "")
            if argv[:2] == ("podman", "pull"):
                self.base_available = True
                return 0, "pulled exact digest", ""
            if argv[:3] == ("podman", "image", "inspect"):
                return 0, "sha256:" + "a" * 64 + "\n", ""
            return 0, "built", ""

    commands = _PullingCommands()
    executor = PodmanQualificationImagePreparationExecutor(command_port=commands)
    action = SimpleNamespace(
        action_id="prepare.batch-1.image-base",
        owner_component_id="openzyme.process.podman",
        effect_id="podman.qualification-image.resolve.base",
        credential_locator_id=None,
        input_binding_digest="sha256:" + "3" * 64,
        safe_input_fields=(SafeIdentityField("image_group", "base"),),
    )

    executor(
        plan=SimpleNamespace(preparation_plan_digest="sha256:" + "1" * 64),
        authorization=SimpleNamespace(authorization_digest="sha256:" + "2" * 64),
        action=action,
        occurrence_id="occurrence.base-image-preparation",
        request_digest="sha256:" + "4" * 64,
        credential_material=None,
    )

    pull_argv = next(
        argv for argv, _cwd in commands.calls if argv[:2] == ("podman", "pull")
    )
    assert pull_argv == (
        "podman",
        "pull",
        "--platform",
        "linux/amd64",
        load_qualification_image_manifest().recipe("base").base_image_ref,
    )
    build_argv = next(
        argv for argv, _cwd in commands.calls if argv[:2] == ("podman", "build")
    )
    assert build_argv[:3] == ("podman", "build", "--pull=never")


def test_bare_podman_image_id_is_normalized_to_canonical_digest() -> None:
    class _BareIdCommands(_Commands):
        def run(
            self, argv: tuple[str, ...], *, working_directory: Path | None = None
        ) -> tuple[int, str, str]:
            self.calls.append((argv, working_directory))
            if argv[:3] == ("podman", "image", "exists"):
                return (0, "", "") if "@sha256:" in argv[-1] else (1, "", "")
            if argv[:3] == ("podman", "image", "inspect"):
                return 0, "b" * 64 + "\n", ""
            return 0, "built", ""

    commands = _BareIdCommands()
    executor = PodmanQualificationImagePreparationExecutor(command_port=commands)
    action = SimpleNamespace(
        action_id="prepare.batch-1.image-base",
        owner_component_id="openzyme.process.podman",
        effect_id="podman.qualification-image.resolve.base",
        credential_locator_id=None,
        input_binding_digest="sha256:" + "3" * 64,
        safe_input_fields=(SafeIdentityField("image_group", "base"),),
    )

    result = executor(
        plan=SimpleNamespace(preparation_plan_digest="sha256:" + "1" * 64),
        authorization=SimpleNamespace(authorization_digest="sha256:" + "2" * 64),
        action=action,
        occurrence_id="occurrence.base-image-preparation",
        request_digest="sha256:" + "4" * 64,
        credential_material=None,
    )

    assert (
        dict((field.field_id, field.value) for field in result.safe_identity_fields)[
            "approved_qualification_image_digest"
        ]
        == "sha256:" + "b" * 64
    )
