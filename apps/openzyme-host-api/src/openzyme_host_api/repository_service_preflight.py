from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import ssl
import stat
import subprocess
import time
from typing import Any
from urllib.parse import urlsplit

from openzyme_core import DurableRepositoryRootManager
from openzyme_core import RepositoryIdentityMismatchError
from openzyme_core import SQLiteRepositoryProvider
from openzyme_domain import ProjectRepositoryBinding
from openzyme_runtime import RepositoryServiceSettings


REPOSITORY_BINDING_INVENTORY_SCHEMA_VERSION = "repository_binding_inventory@1"
REPOSITORY_SERVICE_PREFLIGHT_SCHEMA_VERSION = "repository_service_preflight@1"


class RepositoryServicePreflightError(RuntimeError):
    error_code = "repository_service_preflight_failed"


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _repository_subprocess_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
    }


def build_repository_binding_inventory(
    bindings: tuple[ProjectRepositoryBinding, ...],
) -> dict[str, Any]:
    payload = {
        "schema_version": REPOSITORY_BINDING_INVENTORY_SCHEMA_VERSION,
        "active_bindings": [
            binding.to_dict()
            for binding in sorted(bindings, key=lambda item: item.project_id)
        ],
    }
    return {**payload, "canonical_digest": _sha256_bytes(_canonical_json(payload))}


def load_repository_binding_inventory(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise RepositoryServicePreflightError(
            "repository binding inventory must be a regular file"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepositoryServicePreflightError(
            "repository binding inventory must contain valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "active_bindings",
        "canonical_digest",
    }:
        raise RepositoryServicePreflightError(
            "repository binding inventory has an invalid closed schema"
        )
    if payload["schema_version"] != REPOSITORY_BINDING_INVENTORY_SCHEMA_VERSION:
        raise RepositoryServicePreflightError(
            "repository binding inventory schema version is unsupported"
        )
    if (
        not isinstance(payload["active_bindings"], list)
        or not payload["active_bindings"]
    ):
        raise RepositoryServicePreflightError(
            "repository binding inventory must contain active bindings"
        )
    digest_payload = {
        "schema_version": payload["schema_version"],
        "active_bindings": payload["active_bindings"],
    }
    if payload["canonical_digest"] != _sha256_bytes(_canonical_json(digest_payload)):
        raise RepositoryServicePreflightError(
            "repository binding inventory digest does not match content"
        )
    return payload


def _require_private_file(path: Path, *, field_name: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise RepositoryServicePreflightError(f"{field_name} must be a regular file")
    metadata = path.stat()
    if metadata.st_uid != os.geteuid():
        raise RepositoryServicePreflightError(f"{field_name} has the wrong owner")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RepositoryServicePreflightError(f"{field_name} must have mode 0600")
    return path.read_bytes()


def _binary_digest(path: Path, *, field_name: str) -> str:
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RepositoryServicePreflightError(
            f"configured {field_name} is not an executable file"
        )
    return _sha256_bytes(path.read_bytes())


def _database_fact(provider: SQLiteRepositoryProvider) -> dict[str, object]:
    if provider.uri:
        raise RepositoryServicePreflightError(
            "repository service database must use an explicit filesystem path"
        )
    path = Path(provider.database_path)
    if not path.is_absolute():
        raise RepositoryServicePreflightError(
            "repository service database path must be absolute"
        )
    if not path.is_file() or path.is_symlink():
        raise RepositoryServicePreflightError(
            "repository service database must be a regular file"
        )
    resolved = path.resolve(strict=True)
    metadata = resolved.stat()
    mode = stat.S_IMODE(metadata.st_mode)
    if metadata.st_uid != os.geteuid():
        raise RepositoryServicePreflightError(
            "repository service database has the wrong owner"
        )
    if mode != 0o600:
        raise RepositoryServicePreflightError(
            "repository service database must have mode 0600"
        )
    return {
        "path_digest": _sha256_bytes(str(resolved).encode("utf-8")),
        "owner_uid": metadata.st_uid,
        "owner_gid": metadata.st_gid,
        "mode": f"{mode:04o}",
    }


def _tls_fact(settings: RepositoryServiceSettings) -> dict[str, Any]:
    _require_private_file(settings.tls_private_key_file, field_name="TLS private key")
    if not settings.tls_certificate_file.is_file() or (
        settings.tls_certificate_file.is_symlink()
    ):
        raise RepositoryServicePreflightError("TLS certificate must be a regular file")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        certfile=settings.tls_certificate_file,
        keyfile=settings.tls_private_key_file,
    )
    certificate = ssl._ssl._test_decode_cert(  # noqa: SLF001 - stdlib verifier
        str(settings.tls_certificate_file)
    )
    hostname = urlsplit(settings.https_origin).hostname
    if hostname is None:
        raise RepositoryServicePreflightError("repository HTTPS origin has no hostname")
    subject_alt_names = certificate.get("subjectAltName")
    if not isinstance(subject_alt_names, tuple):
        raise RepositoryServicePreflightError(
            "TLS certificate has no subjectAltName extension"
        )
    try:
        expected_ip = ipaddress.ip_address(hostname)
    except ValueError:
        dns_names = {
            value.rstrip(".").lower()
            for kind, value in subject_alt_names
            if kind == "DNS"
        }
        if hostname.rstrip(".").lower() not in dns_names:
            raise RepositoryServicePreflightError(
                "TLS certificate subjectAltName does not match HTTPS hostname"
            )
    else:
        ip_addresses = {
            ipaddress.ip_address(value)
            for kind, value in subject_alt_names
            if kind == "IP Address"
        }
        if expected_ip not in ip_addresses:
            raise RepositoryServicePreflightError(
                "TLS certificate subjectAltName does not match HTTPS address"
            )
    not_after = certificate.get("notAfter")
    if not isinstance(not_after, str):
        raise RepositoryServicePreflightError("TLS certificate has no expiration time")
    if ssl.cert_time_to_seconds(not_after) <= time.time():
        raise RepositoryServicePreflightError("TLS certificate is expired")
    pem = settings.tls_certificate_file.read_text(encoding="ascii")
    der = ssl.PEM_cert_to_DER_cert(pem)
    return {
        "hostname": hostname,
        "not_after": not_after,
        "certificate_sha256": _sha256_bytes(der),
    }


@dataclass(frozen=True, slots=True)
class RepositoryServicePreflightReport:
    database: dict[str, object]
    root_facts: tuple[dict[str, object], ...]
    active_bindings: tuple[dict[str, object], ...]
    inventory_digest: str
    git_version: str
    git_binary_digest: str
    git_lfs_version: str
    git_lfs_binary_digest: str
    git_http_backend_digest: str
    pre_receive_hook_digest: str
    tls: dict[str, Any]
    schema_version: str = REPOSITORY_SERVICE_PREFLIGHT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "database": self.database,
            "root_facts": list(self.root_facts),
            "active_bindings": list(self.active_bindings),
            "inventory_digest": self.inventory_digest,
            "git_version": self.git_version,
            "git_binary_digest": self.git_binary_digest,
            "git_lfs_version": self.git_lfs_version,
            "git_lfs_binary_digest": self.git_lfs_binary_digest,
            "git_http_backend_digest": self.git_http_backend_digest,
            "pre_receive_hook_digest": self.pre_receive_hook_digest,
            "tls": self.tls,
        }


def preflight_repository_service(
    *,
    settings: RepositoryServiceSettings,
    provider: SQLiteRepositoryProvider,
    roots: DurableRepositoryRootManager,
) -> RepositoryServicePreflightReport:
    database = _database_fact(provider)
    root_facts = roots.preflight_roots()
    _require_private_file(
        settings.credential_signing_key_file,
        field_name="repository credential signing key",
    )
    git_digest = _binary_digest(settings.git_executable, field_name="Git executable")
    git_lfs_digest = _binary_digest(
        settings.git_lfs_executable,
        field_name="git-lfs executable",
    )
    backend_digest = _binary_digest(
        settings.git_http_backend,
        field_name="git-http-backend",
    )
    git_version = subprocess.run(
        (str(settings.git_executable), "--version"),
        check=True,
        capture_output=True,
        env=_repository_subprocess_environment(),
        text=True,
    ).stdout.strip()
    git_lfs_version = subprocess.run(
        (str(settings.git_lfs_executable), "version"),
        check=True,
        capture_output=True,
        env=_repository_subprocess_environment(),
        text=True,
    ).stdout.strip()
    git_exec_path = subprocess.run(
        (str(settings.git_executable), "--exec-path"),
        check=True,
        capture_output=True,
        env=_repository_subprocess_environment(),
        text=True,
    ).stdout.strip()
    if settings.git_http_backend.resolve(strict=True) != (
        Path(git_exec_path) / "git-http-backend"
    ).resolve(strict=True):
        raise RepositoryServicePreflightError(
            "git-http-backend does not belong to the configured Git installation"
        )

    with provider.read() as scope:
        bindings = tuple(scope.repositories.project_repository_bindings.list_active())
        lfs_policies = {
            (binding.binding_id, binding.binding_version): (
                scope.repositories.git_lfs.get_policy(
                    binding_id=binding.binding_id,
                    binding_version=binding.binding_version,
                )
            )
            for binding in bindings
        }
    if not bindings:
        raise RepositoryIdentityMismatchError(
            "repository service has no active project binding"
        )
    inventory = load_repository_binding_inventory(settings.binding_inventory_file)
    expected_inventory = build_repository_binding_inventory(bindings)
    if inventory != expected_inventory:
        raise RepositoryServicePreflightError(
            "repository binding inventory does not match active persisted bindings"
        )

    origin = settings.https_origin.rstrip("/")
    binding_facts: list[dict[str, object]] = []
    for binding in bindings:
        lfs_policy = lfs_policies[(binding.binding_id, binding.binding_version)]
        if (
            lfs_policy is None
            or lfs_policy.repository_id != binding.repository_id
            or lfs_policy.lfs_service_id != binding.lfs_service_id
            or lfs_policy.lfs_endpoint != binding.lfs_endpoint
            or lfs_policy.policy_version != binding.repository_policy_version
            or lfs_policy.policy_digest != binding.repository_policy_digest
        ):
            raise RepositoryServicePreflightError(
                "active binding has no exact immutable Git LFS policy"
            )
        if binding.internal_git_endpoint != (
            f"{origin}/repositories/{binding.repository_id}.git"
        ):
            raise RepositoryServicePreflightError(
                "active binding Git endpoint does not match HTTPS service origin"
            )
        if binding.lfs_endpoint != f"{binding.internal_git_endpoint}/info/lfs":
            raise RepositoryServicePreflightError(
                "active binding LFS endpoint does not match HTTPS service origin"
            )
        roots.verify_exact_base(binding)
        roots.verify_default_head(binding)
        roots.verify_pre_receive_hook(binding)
        binding_facts.append(
            {
                "project_id": binding.project_id,
                "binding_id": binding.binding_id,
                "binding_version": binding.binding_version,
                "repository_id": binding.repository_id,
                "object_format": binding.object_format.value,
                "base_commit": binding.default_base_commit,
                "policy_digest": binding.repository_policy_digest,
                "lfs_object_format": lfs_policy.object_format,
                "ordinary_blob_threshold_bytes": (
                    lfs_policy.ordinary_blob_threshold_bytes
                ),
                "max_object_bytes": lfs_policy.max_object_bytes,
                "max_workspace_bytes": lfs_policy.max_workspace_bytes,
                "max_repository_bytes": lfs_policy.max_repository_bytes,
                "private_retention_seconds": lfs_policy.private_retention_seconds,
            }
        )

    return RepositoryServicePreflightReport(
        database=database,
        root_facts=tuple(fact.to_safe_dict() for fact in root_facts),
        active_bindings=tuple(binding_facts),
        inventory_digest=str(inventory["canonical_digest"]),
        git_version=git_version,
        git_binary_digest=git_digest,
        git_lfs_version=git_lfs_version,
        git_lfs_binary_digest=git_lfs_digest,
        git_http_backend_digest=backend_digest,
        pre_receive_hook_digest=roots.pre_receive_hook_digest(),
        tls=_tls_fact(settings),
    )


__all__ = [
    "REPOSITORY_BINDING_INVENTORY_SCHEMA_VERSION",
    "REPOSITORY_SERVICE_PREFLIGHT_SCHEMA_VERSION",
    "RepositoryServicePreflightError",
    "RepositoryServicePreflightReport",
    "build_repository_binding_inventory",
    "load_repository_binding_inventory",
    "preflight_repository_service",
]
