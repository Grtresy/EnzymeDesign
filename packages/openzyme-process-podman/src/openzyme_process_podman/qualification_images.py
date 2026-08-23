from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from importlib.resources import as_file
from importlib.resources import files
import json
from pathlib import Path
import re
import subprocess
from typing import Protocol

from openzyme_contracts import ExternalIdentityPreparationAction
from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization
from openzyme_contracts import ExternalIdentityPreparationPlan
from openzyme_contracts import ExternalIdentityPreparationResult
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import SafeIdentityField
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import create_external_identity_preparation_success
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


QUALIFICATION_IMAGE_MANIFEST_SCHEMA = "openzyme_qualification_image_manifest@1"
QUALIFICATION_IMAGE_GROUPS = ("base", "docking", "hmmer")
_IMAGE_DIGEST_REF = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_OUTPUT_REF = re.compile(r"localhost/openzyme-qualification-[a-z-]+:[0-9A-Za-z.-]+")
_PRIVATE_OUTPUT_LIMIT = 8192


def _bounded_private_output(value: str) -> tuple[str, bool]:
    if len(value) <= _PRIVATE_OUTPUT_LIMIT:
        return value, False
    half = _PRIVATE_OUTPUT_LIMIT // 2
    return value[:half] + "\n...<bounded>...\n" + value[-half:], True


class QualificationImageCommandFailure(ExternalQualificationError):
    """Private diagnostic carrier for one terminal Podman preparation failure."""

    def __init__(
        self,
        *,
        error_code: str,
        message: str,
        occurrence_id: str,
        image_group: str,
        phase: str,
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        super().__init__(
            error_code,
            message,
            diagnostic_id=f"diagnostic.{occurrence_id}.{phase}",
        )
        self.component = "openzyme.process.podman"
        self.phase = phase
        self.image_group = image_group
        self.returncode = returncode
        self.bounded_stdout, self.stdout_truncated = _bounded_private_output(stdout)
        self.bounded_stderr, self.stderr_truncated = _bounded_private_output(stderr)
        self.effect_certainty = "partial_residual_observed"
        self.mutation_applied = True


@dataclass(frozen=True, slots=True)
class QualificationImageSource:
    source_id: str
    url: str
    version: str
    commit: str

    def __post_init__(self) -> None:
        require_identifier(self.source_id, field_name="source_id")
        if not self.url.startswith("https://github.com/") or not self.url.endswith(
            ".git"
        ):
            raise ValueError(
                "qualification image source must be one official HTTPS Git URL"
            )
        if not self.version or _COMMIT.fullmatch(self.commit) is None:
            raise ValueError("qualification image source must bind version and commit")

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "url": self.url,
            "version": self.version,
            "commit": self.commit,
        }


@dataclass(frozen=True, slots=True)
class QualificationImageRecipe:
    image_group: str
    containerfile_name: str
    containerfile_digest: str
    output_image_ref: str
    base_image_ref: str
    platform: str
    uv_lock_digest: str
    sources: tuple[QualificationImageSource, ...]
    expected_versions: tuple[tuple[str, str], ...]
    recipe_digest: str

    def __post_init__(self) -> None:
        if self.image_group not in QUALIFICATION_IMAGE_GROUPS:
            raise ValueError("unsupported qualification image group")
        if _IMAGE_DIGEST_REF.fullmatch(self.base_image_ref) is None:
            raise ValueError("qualification base image must be digest pinned")
        if _OUTPUT_REF.fullmatch(self.output_image_ref) is None:
            raise ValueError("qualification output image must be repository-owned")
        if self.platform != "linux/amd64":
            raise ValueError("qualification images are frozen to linux/amd64")
        for value, name in (
            (self.containerfile_digest, "containerfile_digest"),
            (self.uv_lock_digest, "uv_lock_digest"),
            (self.recipe_digest, "recipe_digest"),
        ):
            require_digest(value, field_name=name)
        if len({item.source_id for item in self.sources}) != len(self.sources):
            raise ValueError("qualification image sources must be unique")
        if not self.expected_versions:
            raise ValueError("qualification image versions cannot be empty")
        if self.recipe_digest != canonical_sha256_digest(self.identity_payload):
            raise ExternalQualificationError(
                "qualification_image_recipe_digest_mismatch",
                "qualification image recipe digest does not match its inputs",
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "openzyme_qualification_image_recipe@1",
            "image_group": self.image_group,
            "containerfile_name": self.containerfile_name,
            "containerfile_digest": self.containerfile_digest,
            "output_image_ref": self.output_image_ref,
            "base_image_ref": self.base_image_ref,
            "platform": self.platform,
            "uv_lock_digest": self.uv_lock_digest,
            "sources": [item.to_dict() for item in self.sources],
            "expected_versions": dict(self.expected_versions),
        }

    def build_argv(self, *, podman_binary: str = "podman") -> tuple[str, ...]:
        arguments = [
            podman_binary,
            "build",
            "--pull=never",
            "--memory=2048m",
            "--platform",
            self.platform,
            "--label",
            f"io.openzyme.qualification.recipe-digest={self.recipe_digest}",
            "--build-arg",
            f"BASE_IMAGE_REF={self.base_image_ref}",
        ]
        for source in self.sources:
            argument_name = {
                "hmmer": "HMMER_COMMIT",
                "autodock_vina": "VINA_COMMIT",
                "fpocket": "FPOCKET_COMMIT",
            }[source.source_id]
            arguments.extend(("--build-arg", f"{argument_name}={source.commit}"))
        arguments.extend(
            (
                "--file",
                self.containerfile_name,
                "--tag",
                self.output_image_ref,
                ".",
            )
        )
        return tuple(arguments)


@dataclass(frozen=True, slots=True)
class QualificationImageManifest:
    manifest_id: str
    recipes: tuple[QualificationImageRecipe, ...]
    manifest_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.manifest_id, field_name="manifest_id")
        if tuple(sorted(item.image_group for item in self.recipes)) != (
            "base",
            "docking",
            "hmmer",
        ):
            raise ValueError("qualification manifest must contain exactly three groups")
        require_digest(self.manifest_digest, field_name="manifest_digest")
        if self.manifest_digest != canonical_sha256_digest(self.identity_payload):
            raise ExternalQualificationError(
                "qualification_image_manifest_digest_mismatch",
                "qualification image manifest digest does not match its recipes",
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": QUALIFICATION_IMAGE_MANIFEST_SCHEMA,
            "manifest_id": self.manifest_id,
            "recipes": [item.identity_payload for item in self.recipes],
        }

    def recipe(self, image_group: str) -> QualificationImageRecipe:
        try:
            return next(
                item for item in self.recipes if item.image_group == image_group
            )
        except StopIteration as exc:
            raise ExternalQualificationError(
                "qualification_image_group_unknown",
                "image group is outside the exact qualification manifest",
            ) from exc


class QualificationImageCommandPort(Protocol):
    def run(
        self, argv: tuple[str, ...], *, working_directory: Path | None = None
    ) -> tuple[int, str, str]: ...


@dataclass(frozen=True, slots=True)
class SubprocessQualificationImageCommandPort:
    def run(
        self, argv: tuple[str, ...], *, working_directory: Path | None = None
    ) -> tuple[int, str, str]:
        try:
            completed = subprocess.run(
                argv,
                cwd=working_directory,
                check=False,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExternalQualificationError(
                "qualification_image_build_timeout",
                "qualification image command exceeded the exact hard time limit",
            ) from exc
        return completed.returncode, completed.stdout, completed.stderr


@dataclass(frozen=True, slots=True)
class PodmanQualificationImagePreparationExecutor:
    command_port: QualificationImageCommandPort = field(repr=False)
    manifest: QualificationImageManifest = field(
        default_factory=lambda: load_qualification_image_manifest()
    )

    def __call__(
        self,
        *,
        plan: ExternalIdentityPreparationPlan,
        authorization: ExternalIdentityPreparationOccurrenceAuthorization,
        action: ExternalIdentityPreparationAction,
        occurrence_id: str,
        request_digest: str,
        credential_material: object | None,
    ) -> ExternalIdentityPreparationResult:
        if (
            action.owner_component_id != "openzyme.process.podman"
            or action.credential_locator_id is not None
            or credential_material is not None
        ):
            raise ExternalQualificationError(
                "qualification_image_preparation_binding_mismatch",
                "Podman image preparation differs from the exact planned action",
            )
        inputs = {item.field_id: item.value for item in action.safe_input_fields}
        image_group = inputs.get("image_group", "")
        if action.effect_id != f"podman.qualification-image.resolve.{image_group}":
            raise ExternalQualificationError(
                "qualification_image_preparation_binding_mismatch",
                "Podman image effect does not bind the exact manifest group",
            )
        recipe = self.manifest.recipe(image_group)
        exists_argv = ("podman", "image", "exists", recipe.output_image_ref)
        returncode, _stdout, _stderr = self.command_port.run(exists_argv)
        if returncode == 0:
            raise ExternalQualificationError(
                "qualification_image_output_already_exists",
                "qualification image output requires operator reconciliation before build",
            )
        if returncode != 1:
            raise ExternalQualificationError(
                "qualification_image_preflight_failed",
                "qualification image output state could not be determined",
            )
        base_exists_argv = ("podman", "image", "exists", recipe.base_image_ref)
        returncode, _stdout, _stderr = self.command_port.run(base_exists_argv)
        if returncode == 1:
            returncode, stdout, stderr = self.command_port.run(
                (
                    "podman",
                    "pull",
                    "--platform",
                    recipe.platform,
                    recipe.base_image_ref,
                )
            )
            if returncode != 0:
                raise QualificationImageCommandFailure(
                    error_code="qualification_image_base_pull_failed",
                    message="digest-pinned qualification base image pull failed",
                    occurrence_id=occurrence_id,
                    image_group=image_group,
                    phase="qualification-base-image-pull",
                    returncode=returncode,
                    stdout=stdout,
                    stderr=stderr,
                )
            returncode, _stdout, _stderr = self.command_port.run(base_exists_argv)
        if returncode != 0:
            raise ExternalQualificationError(
                "qualification_image_base_digest_unavailable",
                "digest-pinned qualification base image is unavailable after resolution",
            )
        asset_root = files("openzyme_process_podman.qualification_image_assets")
        with as_file(asset_root) as context_root:
            returncode, stdout, stderr = self.command_port.run(
                recipe.build_argv(),
                working_directory=context_root,
            )
        if returncode != 0:
            raise QualificationImageCommandFailure(
                error_code="qualification_image_build_failed",
                message="repository-owned qualification image build failed",
                occurrence_id=occurrence_id,
                image_group=image_group,
                phase="qualification-image-build",
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            )
        inspect_argv = (
            "podman",
            "image",
            "inspect",
            "--format={{.Id}}",
            recipe.output_image_ref,
        )
        returncode, stdout, _stderr = self.command_port.run(inspect_argv)
        image_digest = stdout.strip()
        if (
            returncode != 0
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None
        ):
            raise ExternalQualificationError(
                "qualification_image_digest_observation_failed",
                "built qualification image did not expose one immutable image digest",
            )
        versions = dict(recipe.expected_versions)
        if image_group == "base":
            field_pairs = (
                ("approved_qualification_image_digest", image_digest),
                (
                    "container_policy_digest",
                    canonical_sha256_digest(
                        {
                            "manifest_digest": self.manifest.manifest_digest,
                            "recipe_digest": recipe.recipe_digest,
                            "platform": recipe.platform,
                            "pull_policy": "never",
                        }
                    ),
                ),
            )
        elif image_group == "hmmer":
            field_pairs = (
                ("hmmer_image_digest", image_digest),
                ("hmmer_version", versions["hmmer"]),
            )
        else:
            field_pairs = (
                ("fpocket_image_digest", image_digest),
                ("fpocket_version", versions["fpocket"]),
                ("meeko_version", versions["meeko"]),
                ("openbabel_version", versions["openbabel"]),
                ("preprocess_image_digest", image_digest),
                ("rdkit_version", versions["rdkit"]),
                ("vina_image_digest", image_digest),
                ("vina_version", versions["vina"]),
            )
        fields = tuple(
            SafeIdentityField(field_id, value)
            for field_id, value in sorted(field_pairs)
        )
        return create_external_identity_preparation_success(
            occurrence_id=occurrence_id,
            preparation_plan_digest=plan.preparation_plan_digest,
            authorization_digest=authorization.authorization_digest,
            action_id=action.action_id,
            owner_component_id=action.owner_component_id,
            effect_id=action.effect_id,
            input_binding_digest=action.input_binding_digest,
            request_digest=request_digest,
            safe_identity_fields=fields,
            receipt_payload={
                "schema_version": "podman_qualification_image_preparation_receipt@1",
                "occurrence_id": occurrence_id,
                "image_group": image_group,
                "image_digest": image_digest,
                "manifest_digest": self.manifest.manifest_digest,
                "recipe_digest": recipe.recipe_digest,
            },
            external_effect_performed=True,
            credential_material_accessed=False,
        )

    def cleanup(self, image_group: str) -> None:
        recipe = self.manifest.recipe(image_group)
        returncode, _stdout, _stderr = self.command_port.run(
            ("podman", "image", "rm", recipe.output_image_ref)
        )
        if returncode != 0:
            raise ExternalQualificationError(
                "qualification_image_cleanup_failed",
                "qualification image cleanup failed",
            )


def load_qualification_image_manifest() -> QualificationImageManifest:
    root = files("openzyme_process_podman.qualification_image_assets")
    payload = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != QUALIFICATION_IMAGE_MANIFEST_SCHEMA:
        raise ValueError("unsupported qualification image manifest schema")
    base_image_ref = str(payload["base_image_ref"])
    platform = str(payload["platform"])
    uv_lock_digest = str(payload["uv_lock_digest"])
    recipes = []
    for item in payload["recipes"]:
        containerfile_name = str(item["containerfile"])
        containerfile = root.joinpath(containerfile_name).read_bytes()
        containerfile_digest = (
            "sha256:" + __import__("hashlib").sha256(containerfile).hexdigest()
        )
        sources = tuple(
            QualificationImageSource(
                source_id=str(source["source_id"]),
                url=str(source["url"]),
                version=str(source["version"]),
                commit=str(source["commit"]),
            )
            for source in item["sources"]
        )
        identity_payload = {
            "schema_version": "openzyme_qualification_image_recipe@1",
            "image_group": str(item["image_group"]),
            "containerfile_name": containerfile_name,
            "containerfile_digest": containerfile_digest,
            "output_image_ref": str(item["output_image_ref"]),
            "base_image_ref": base_image_ref,
            "platform": platform,
            "uv_lock_digest": uv_lock_digest,
            "sources": [source.to_dict() for source in sources],
            "expected_versions": dict(sorted(item["expected_versions"].items())),
        }
        recipes.append(
            QualificationImageRecipe(
                image_group=str(item["image_group"]),
                containerfile_name=containerfile_name,
                containerfile_digest=containerfile_digest,
                output_image_ref=str(item["output_image_ref"]),
                base_image_ref=base_image_ref,
                platform=platform,
                uv_lock_digest=uv_lock_digest,
                sources=sources,
                expected_versions=tuple(sorted(item["expected_versions"].items())),
                recipe_digest=canonical_sha256_digest(identity_payload),
            )
        )
    canonical_recipes = tuple(sorted(recipes, key=lambda recipe: recipe.image_group))
    identity_payload = {
        "schema_version": QUALIFICATION_IMAGE_MANIFEST_SCHEMA,
        "manifest_id": str(payload["manifest_id"]),
        "recipes": [recipe.identity_payload for recipe in canonical_recipes],
    }
    return QualificationImageManifest(
        manifest_id=str(payload["manifest_id"]),
        recipes=canonical_recipes,
        manifest_digest=canonical_sha256_digest(identity_payload),
    )


__all__ = [
    "QUALIFICATION_IMAGE_GROUPS",
    "QUALIFICATION_IMAGE_MANIFEST_SCHEMA",
    "QualificationImageCommandPort",
    "QualificationImageManifest",
    "PodmanQualificationImagePreparationExecutor",
    "QualificationImageRecipe",
    "QualificationImageSource",
    "SubprocessQualificationImageCommandPort",
    "load_qualification_image_manifest",
]
