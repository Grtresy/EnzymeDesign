from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping

from openzyme_runtime import canonical_digest
from openzyme_runtime import load_env_files
from openzyme_runtime import openzyme_settings_environment_contract
from openzyme_runtime import openzyme_settings_source_projection
from openzyme_runtime import resolve_live_micu_token_ledger_path
from openzyme_runtime import resolve_openzyme_settings_environment_field

from .aox_cutover_runtime_config import aox_environment_profile_requirements
from .aox_cutover_runtime_config import (
    validate_aox_environment_profile_requirements,
)


AOX_CONFIG_CONTRACT_SCHEMA_ID = "aox_config_contract@1"
AOX_CONFIG_CANDIDATE_SCHEMA_ID = "aox_config_candidate@1"

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_CANDIDATE_ID_PATTERN = re.compile(r"^aox-config-[0-9a-f]{32}$")
_CANDIDATE_FIELDS = frozenset(
    {
        "schema_id",
        "contract_digest",
        "candidate_id",
        "profile_source_digest",
        "ledger_identity_digest",
        "runner_config_identity_digest",
    }
)


class AoxConfigContractError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def aox_config_contract() -> dict[str, object]:
    """Return the executable profile descriptor and candidate lifecycle contract."""

    environment_fields = openzyme_settings_environment_contract()
    eligibility = aox_environment_profile_requirements()
    try:
        validate_aox_environment_profile_requirements(eligibility)
    except ValueError as exc:
        raise AoxConfigContractError(
            "aox_config_contract_source_drift",
            "AOX eligibility drifted from runtime normalization",
        ) from exc
    field_paths = {str(field["setting_path"]) for field in environment_fields}
    missing_fields = sorted(set(eligibility) - field_paths)
    if missing_fields:
        raise AoxConfigContractError(
            "aox_config_contract_source_drift",
            "AOX eligibility references settings absent from the canonical resolver: "
            + ", ".join(missing_fields),
        )
    profile_fields = [
        {
            **field,
            "aox_eligibility": eligibility.get(
                str(field["setting_path"]),
                {
                    "safe_generic_default_eligible": True,
                    "requirements": [
                        {"kind": ("generic_descriptor_and_effective_config_validation")}
                    ],
                },
            ),
        }
        for field in environment_fields
    ]

    payload: dict[str, object] = {
        "schema_id": AOX_CONFIG_CONTRACT_SCHEMA_ID,
        "capability_id": "aox.config-candidate",
        "profile_source": "OpenZymeSettings.from_env",
        "candidate_schema_id": AOX_CONFIG_CANDIDATE_SCHEMA_ID,
        "candidate_identity": (
            "credential_presence_and_canonical_value_digest_of_exact_profile_sources"
        ),
        "profile_descriptor_owner": (
            "openzyme_runtime.settings.openzyme_settings_environment_contract"
        ),
        "effective_config_validation_owner": (
            "openzyme_host_api.aox_cutover_runtime_config."
            "normalize_aox_blank_world_runtime_config"
        ),
        "profile_source_projection": {
            "credential_values": "presence_only",
            "private_values": "canonical_value_digest",
            "non_sensitive_values": "canonical_resolved_value",
            "paths": "separate_resolved_path_and_content_identity",
            "unlisted_environment": "ignored",
            "invalid_non_sensitive_input": "input_digest",
        },
        "profile_fields": profile_fields,
        "derived_requirements": [
            {
                "identity": "host.storage_profile",
                "source": "sealed_effective_config_builder",
                "kind": "exact_value",
                "value": "single_process_sqlite",
            },
            {
                "identity": "host.background_runtime_enabled",
                "source": "sealed_effective_config_builder",
                "kind": "exact_value",
                "value": False,
            },
            {
                "identity": "research.mcp_enabled",
                "source": "sealed_effective_config_builder",
                "kind": "exact_value",
                "value": True,
            },
        ],
        "publication": "atomic_no_replace",
        "publication_terminal_scope": "config_candidate_publication_occurrence",
        "publication_failure_effect_certainties": ["no_effect", "unproven"],
        "publication_unproven_retry_eligibility": "reconcile_required",
        "publication_unproven_reconciliation_required": True,
        "validation_effect_certainty": "no_effect",
        "validation_retry_eligibility": "terminal",
        "validation_terminal_scope": "config_candidate_occurrence",
        "replacement_gate": "new_candidate_identity_required",
        "forbidden_fallbacks": [
            "automatic_profile_rewrite",
            "automatic_validation_retry",
            "reuse_rejected_candidate_identity",
            "runner_or_provider_probe",
        ],
    }
    return {**payload, "contract_digest": canonical_digest(payload)}


def _path_identity(raw: str | Path | None) -> str:
    if raw in {None, ""}:
        return canonical_digest({"configured": False})
    path = Path(str(raw)).expanduser()
    payload: dict[str, object] = {
        "configured": True,
        "path_digest": canonical_digest(str(path.absolute())),
    }
    try:
        resolved = path.resolve(strict=True)
        payload.update(
            {
                "resolved_path_digest": canonical_digest(str(resolved)),
                "regular_file": resolved.is_file() and not resolved.is_symlink(),
                "content_digest": (
                    "sha256:" + hashlib.sha256(resolved.read_bytes()).hexdigest()
                    if resolved.is_file() and not resolved.is_symlink()
                    else None
                ),
            }
        )
    except OSError:
        payload["resolvable"] = False
    return canonical_digest(payload)


def build_aox_config_candidate(
    *,
    ledger_path: Path | None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Snapshot one credential-free, source-bound profile candidate.

    Loading env files is deliberately part of construction, while semantic
    validation is not.  A malformed candidate can therefore still receive an
    identity and be rejected as exactly that occurrence by ``check-config``.
    """

    if environ is None:
        load_env_files()
        source_environment = os.environ
    else:
        source_environment = environ
    source_projection = openzyme_settings_source_projection(source_environment)
    configured_ledger_value = resolve_openzyme_settings_environment_field(
        "test.live_llm.token_ledger_path",
        source_environment,
    )
    configured_ledger = (
        ledger_path
        if ledger_path is not None
        else resolve_live_micu_token_ledger_path(str(configured_ledger_value))
    )
    runner_config = resolve_openzyme_settings_environment_field(
        "execution.hpc_runner_config",
        source_environment,
    )
    contract = aox_config_contract()
    profile_source_digest = canonical_digest(source_projection)
    ledger_identity_digest = _path_identity(configured_ledger)
    runner_config_identity_digest = _path_identity(runner_config)
    identity_digest = canonical_digest(
        {
            "contract_digest": contract["contract_digest"],
            "profile_source_digest": profile_source_digest,
            "ledger_identity_digest": ledger_identity_digest,
            "runner_config_identity_digest": runner_config_identity_digest,
        }
    )
    return {
        "schema_id": AOX_CONFIG_CANDIDATE_SCHEMA_ID,
        "contract_digest": str(contract["contract_digest"]),
        "candidate_id": "aox-config-" + identity_digest.removeprefix("sha256:")[:32],
        "profile_source_digest": profile_source_digest,
        "ledger_identity_digest": ledger_identity_digest,
        "runner_config_identity_digest": runner_config_identity_digest,
    }


def normalize_aox_config_candidate(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != _CANDIDATE_FIELDS:
        raise AoxConfigContractError(
            "aox_config_candidate_schema_invalid",
            "AOX config candidate has an unknown field set",
        )
    normalized = {key: str(value) for key, value in payload.items()}
    if normalized["schema_id"] != AOX_CONFIG_CANDIDATE_SCHEMA_ID:
        raise AoxConfigContractError(
            "aox_config_candidate_schema_invalid",
            "AOX config candidate schema is unsupported",
        )
    if normalized["contract_digest"] != aox_config_contract()["contract_digest"]:
        raise AoxConfigContractError(
            "aox_config_candidate_contract_drift",
            "AOX config candidate was not constructed from the current contract",
        )
    if _CANDIDATE_ID_PATTERN.fullmatch(normalized["candidate_id"]) is None or any(
        _DIGEST_PATTERN.fullmatch(normalized[key]) is None
        for key in (
            "contract_digest",
            "profile_source_digest",
            "ledger_identity_digest",
            "runner_config_identity_digest",
        )
    ):
        raise AoxConfigContractError(
            "aox_config_candidate_identity_invalid",
            "AOX config candidate identity is malformed",
        )
    expected_identity = canonical_digest(
        {
            "contract_digest": normalized["contract_digest"],
            "profile_source_digest": normalized["profile_source_digest"],
            "ledger_identity_digest": normalized["ledger_identity_digest"],
            "runner_config_identity_digest": normalized[
                "runner_config_identity_digest"
            ],
        }
    )
    if normalized["candidate_id"] != (
        "aox-config-" + expected_identity.removeprefix("sha256:")[:32]
    ):
        raise AoxConfigContractError(
            "aox_config_candidate_identity_invalid",
            "AOX config candidate identity does not bind its source digests",
        )
    return normalized


def load_aox_config_candidate(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AoxConfigContractError(
            "aox_config_candidate_unreadable",
            "AOX config candidate is not readable canonical JSON",
        ) from exc
    return normalize_aox_config_candidate(payload)


def require_current_aox_config_candidate(
    candidate: Mapping[str, object],
    *,
    ledger_path: Path | None,
) -> dict[str, str]:
    normalized = normalize_aox_config_candidate(dict(candidate))
    current = build_aox_config_candidate(ledger_path=ledger_path)
    if normalized != current:
        raise AoxConfigContractError(
            "aox_config_candidate_source_drift",
            "AOX config sources changed after candidate construction",
        )
    return normalized


def publish_aox_config_candidate(path: Path, payload: object) -> Path:
    """Publish one normalized candidate atomically without replacement."""

    normalized = normalize_aox_config_candidate(payload)
    target = path.expanduser().absolute()
    try:
        parent = target.parent.resolve(strict=True)
    except OSError as exc:
        raise AoxConfigContractError(
            "aox_config_candidate_output_parent_invalid",
            "AOX config candidate output parent is not an existing directory",
        ) from exc
    if target.parent != parent or parent.is_symlink() or not parent.is_dir():
        raise AoxConfigContractError(
            "aox_config_candidate_output_parent_invalid",
            "AOX config candidate output parent is not a real directory",
        )
    content = (
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".openzyme-aox-config-",
        suffix=".tmp",
        dir=parent,
    )
    temporary = Path(temporary_name)
    installed = False
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("AOX config candidate write made no progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, target, follow_symlinks=False)
        installed = True
        _fsync_directory(parent)
    except FileExistsError as exc:
        raise AoxConfigContractError(
            "aox_config_candidate_output_exists",
            "AOX config candidate output already exists",
        ) from exc
    except OSError as exc:
        if installed:
            try:
                target.unlink()
                _fsync_directory(parent)
            except OSError as cleanup_exc:
                raise AoxConfigContractError(
                    "aox_config_candidate_publication_in_doubt",
                    "AOX config candidate publication effect is not proven",
                ) from cleanup_exc
        raise AoxConfigContractError(
            "aox_config_candidate_output_write_failed",
            "AOX config candidate output could not be published atomically",
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return target


__all__ = [
    "AOX_CONFIG_CANDIDATE_SCHEMA_ID",
    "AOX_CONFIG_CONTRACT_SCHEMA_ID",
    "AoxConfigContractError",
    "aox_config_contract",
    "build_aox_config_candidate",
    "load_aox_config_candidate",
    "normalize_aox_config_candidate",
    "publish_aox_config_candidate",
    "require_current_aox_config_candidate",
]
