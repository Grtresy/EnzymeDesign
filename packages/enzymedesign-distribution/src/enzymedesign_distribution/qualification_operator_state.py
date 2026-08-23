from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import json
import os
from pathlib import Path
import stat
from typing import Mapping

from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier


QUALIFICATION_STATE_ROOT_ENV = "OPENZYME_QUALIFICATION_STATE_ROOT"
QUALIFICATION_OPERATOR_LAYOUT_SCHEMA = "enzymedesign_qualification_operator_layout@1"
QUALIFICATION_CREDENTIAL_BUNDLE_SCHEMA = (
    "enzymedesign_qualification_credential_bundle@1"
)


def _validate_private_path(
    path: Path,
    *,
    expected_mode: int,
    directory: bool,
) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ExternalQualificationError(
            "qualification_operator_state_missing",
            "protected qualification operator state is not provisioned",
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ExternalQualificationError(
            "qualification_operator_state_symlink_forbidden",
            "protected qualification operator state cannot use symlinks",
        )
    expected_kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_kind(metadata.st_mode):
        raise ExternalQualificationError(
            "qualification_operator_state_kind_invalid",
            "protected qualification operator state has the wrong filesystem kind",
        )
    if (
        metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != expected_mode
    ):
        raise ExternalQualificationError(
            "qualification_operator_state_permissions_unsafe",
            "protected qualification operator state ownership or mode is unsafe",
        )


def _read_object(path: Path, *, allowed_keys: set[str]) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalQualificationError(
            "qualification_operator_state_payload_invalid",
            "protected qualification operator state payload is unreadable",
        ) from exc
    if not isinstance(payload, dict) or set(payload).difference(allowed_keys):
        raise ExternalQualificationError(
            "qualification_operator_state_payload_invalid",
            "protected qualification operator state payload has unsupported fields",
        )
    return payload


@dataclass(frozen=True, slots=True)
class QualificationOperatorStateLayout:
    layout_id: str
    root: Path = field(repr=False)
    credential_bundle_path: Path = field(repr=False)
    ledger_path: Path = field(repr=False)
    private_evidence_root: Path = field(repr=False)
    policy_digest: str

    @classmethod
    def bootstrap(
        cls,
        root: Path,
        *,
        layout_id: str = "qualification.operator-state.primary",
    ) -> "QualificationOperatorStateLayout":
        """Create only the owner-only root and public layout marker.

        Credential material is deliberately outside this operation and must be
        provisioned by the operator through a separate private channel.
        """

        if not root.is_absolute():
            raise ValueError("qualification operator state root must be absolute")
        require_identifier(layout_id, field_name="layout_id")
        candidate = root
        if candidate.exists() or candidate.is_symlink():
            _validate_private_path(candidate, expected_mode=0o700, directory=True)
            layout_path = candidate / "layout.json"
            if layout_path.exists() or layout_path.is_symlink():
                opened = cls.open(candidate)
                if opened.layout_id != layout_id:
                    raise ExternalQualificationError(
                        "qualification_operator_state_layout_mismatch",
                        "existing protected layout has a different identity",
                    )
                return opened
            if any(candidate.iterdir()):
                raise ExternalQualificationError(
                    "qualification_operator_state_not_empty",
                    "uninitialized protected qualification root must be empty",
                )
        else:
            if not candidate.parent.is_dir():
                raise ExternalQualificationError(
                    "qualification_operator_state_parent_missing",
                    "protected qualification root parent must already exist",
                )
            os.mkdir(candidate, mode=0o700)
            candidate.chmod(0o700)

        layout_path = candidate / "layout.json"
        payload = json.dumps(
            {
                "schema_version": QUALIFICATION_OPERATOR_LAYOUT_SCHEMA,
                "layout_id": layout_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        descriptor = os.open(
            layout_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        layout_path.chmod(0o600)
        return cls.open(candidate)

    @classmethod
    def open(cls, root: Path) -> "QualificationOperatorStateLayout":
        if not root.is_absolute():
            raise ValueError("qualification operator state root must be absolute")
        candidate = root
        _validate_private_path(candidate, expected_mode=0o700, directory=True)
        resolved = candidate.resolve(strict=True)
        _validate_private_path(resolved, expected_mode=0o700, directory=True)
        layout_path = resolved / "layout.json"
        _validate_private_path(layout_path, expected_mode=0o600, directory=False)
        payload = _read_object(
            layout_path,
            allowed_keys={"schema_version", "layout_id"},
        )
        if payload.get("schema_version") != QUALIFICATION_OPERATOR_LAYOUT_SCHEMA:
            raise ExternalQualificationError(
                "qualification_operator_state_schema_mismatch",
                "protected qualification operator layout schema is unsupported",
            )
        layout_id = str(payload.get("layout_id", ""))
        require_identifier(layout_id, field_name="layout_id")
        policy_digest = canonical_sha256_digest(
            {
                "schema_version": QUALIFICATION_OPERATOR_LAYOUT_SCHEMA,
                "layout_id": layout_id,
                "root_mode": "0700",
                "private_file_mode": "0600",
                "credential_bundle_filename": "credentials.json",
                "ledger_filename": "qualification.sqlite3",
                "private_evidence_directory": "private-evidence",
                "symlinks_allowed": False,
            }
        )
        return cls(
            layout_id=layout_id,
            root=resolved,
            credential_bundle_path=resolved / "credentials.json",
            ledger_path=resolved / "qualification.sqlite3",
            private_evidence_root=resolved / "private-evidence",
            policy_digest=policy_digest,
        )

    def safe_identity(self) -> dict[str, str]:
        return {
            "layout_id": self.layout_id,
            "policy_digest": self.policy_digest,
            "ledger_id": "qualification.ledger.protected.operator-state-root.sqlite",
            "private_evidence_root_id": (
                "qualification.evidence.protected.operator-state-root"
            ),
        }


@dataclass(frozen=True, slots=True)
class ProtectedQualificationCredentialMaterial:
    locator_id: str
    material_kind: str
    locator_version: str
    _fields: tuple[tuple[str, str], ...] = field(repr=False)

    def __post_init__(self) -> None:
        require_identifier(self.locator_id, field_name="locator_id")
        require_identifier(self.material_kind, field_name="material_kind")
        require_identifier(self.locator_version, field_name="locator_version")
        if not self._fields or len({name for name, _value in self._fields}) != len(
            self._fields
        ):
            raise ValueError("credential material fields must be non-empty and unique")
        for name, value in self._fields:
            require_identifier(name, field_name="credential material field")
            if not isinstance(value, str) or not value:
                raise ValueError("credential material values must be non-empty strings")

    def field_value(self, field_name: str) -> str:
        require_identifier(field_name, field_name="field_name")
        try:
            return dict(self._fields)[field_name]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_credential_material_field_missing",
                "credential material lacks one owner-required field",
            ) from exc

    def __repr__(self) -> str:
        return (
            "ProtectedQualificationCredentialMaterial("
            f"locator_id={self.locator_id!r}, material_kind={self.material_kind!r}, "
            f"locator_version={self.locator_version!r}, field_count={len(self._fields)})"
        )


class ProtectedQualificationCredentialBundleResolver:
    def __init__(
        self,
        *,
        layout: QualificationOperatorStateLayout,
        allowed_locator_ids: tuple[str, ...],
    ) -> None:
        self._layout = layout
        self._allowed_locator_ids = frozenset(allowed_locator_ids)
        for locator_id in self._allowed_locator_ids:
            require_identifier(locator_id, field_name="allowed_locator_id")

    def resolve(self, *, locator_id: str) -> ProtectedQualificationCredentialMaterial:
        if locator_id not in self._allowed_locator_ids:
            raise ExternalQualificationError(
                "qualification_credential_locator_mismatch",
                "credential resolver rejects an unplanned locator before bundle access",
            )
        bundle_path = self._layout.credential_bundle_path
        _validate_private_path(bundle_path, expected_mode=0o600, directory=False)
        payload = _read_object(
            bundle_path,
            allowed_keys={"schema_version", "bundle_id", "locators"},
        )
        if payload.get("schema_version") != QUALIFICATION_CREDENTIAL_BUNDLE_SCHEMA:
            raise ExternalQualificationError(
                "qualification_credential_bundle_schema_mismatch",
                "protected qualification credential bundle schema is unsupported",
            )
        require_identifier(str(payload.get("bundle_id", "")), field_name="bundle_id")
        locators = payload.get("locators")
        if not isinstance(locators, dict):
            raise ExternalQualificationError(
                "qualification_credential_bundle_payload_invalid",
                "protected qualification credential bundle has no locator map",
            )
        entry = locators.get(locator_id)
        if not isinstance(entry, dict) or set(entry) != {
            "material_kind",
            "locator_version",
            "fields",
        }:
            raise ExternalQualificationError(
                "qualification_credential_locator_unavailable",
                "planned credential locator is unavailable in the protected bundle",
            )
        fields = entry.get("fields")
        if not isinstance(fields, dict):
            raise ExternalQualificationError(
                "qualification_credential_bundle_payload_invalid",
                "protected qualification credential fields are malformed",
            )
        return ProtectedQualificationCredentialMaterial(
            locator_id=locator_id,
            material_kind=str(entry["material_kind"]),
            locator_version=str(entry["locator_version"]),
            _fields=tuple(
                sorted((str(name), str(value)) for name, value in fields.items())
            ),
        )


__all__ = [
    "ProtectedQualificationCredentialBundleResolver",
    "ProtectedQualificationCredentialMaterial",
    "QUALIFICATION_CREDENTIAL_BUNDLE_SCHEMA",
    "QUALIFICATION_OPERATOR_LAYOUT_SCHEMA",
    "QUALIFICATION_STATE_ROOT_ENV",
    "QualificationOperatorStateLayout",
]
