from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
from urllib.parse import urlsplit

import uvicorn

from openzyme_core import CURRENT_SQLITE_SCHEMA_VERSION
from openzyme_core import DurableRepositoryRootManager
from openzyme_core import ProjectRepositoryBindingService
from openzyme_core import RepositoryRootBoundary
from openzyme_core import SQLiteRepositoryProvider
from openzyme_domain import ProjectRepositoryBinding
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import RepositoryServiceSettings

from .repository_service_preflight import build_repository_binding_inventory
from .repository_service_preflight import preflight_repository_service
from .repository_restore_rehearsal import rehearse_repository_service_restore
from .repository_transport import RepositoryTransportDependencies
from .repository_transport import create_repository_transport_app


def _repository_settings() -> RepositoryServiceSettings:
    settings = OpenZymeSettings.from_env().repository_service
    if settings is None:
        raise RuntimeError("repository service configuration is required")
    return settings


def _absolute_database_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("database path must be absolute")
    return path


def _absolute_existing_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.exists():
        raise argparse.ArgumentTypeError("path must be absolute and exist")
    return path


def _roots(settings: RepositoryServiceSettings) -> DurableRepositoryRootManager:
    return DurableRepositoryRootManager(
        settings,
        RepositoryRootBoundary.production(
            host_checkout=Path(__file__).resolve().parents[4],
            process_cwd=Path.cwd(),
        ),
    )


def _load_binding(path: Path) -> ProjectRepositoryBinding:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("repository binding file must contain one JSON object")
    return ProjectRepositoryBinding.from_dict(payload)


def _write_inventory(
    settings: RepositoryServiceSettings,
    bindings: tuple[ProjectRepositoryBinding, ...],
) -> dict[str, Any]:
    inventory = build_repository_binding_inventory(bindings)
    destination = settings.binding_inventory_file
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(
        inventory,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    destination.chmod(0o600)
    directory_fd = os.open(destination.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return inventory


def _initialize_binding(args: argparse.Namespace) -> dict[str, Any]:
    settings = _repository_settings()
    roots = _roots(settings)
    binding = _load_binding(args.binding_file)
    roots.preflight_roots()
    roots.create_bare_repository(binding)
    roots.import_exact_commit_from_repository(
        binding,
        source_repository=args.source_repository,
        source_commit=args.source_commit,
    )
    provider = SQLiteRepositoryProvider(str(args.database_path))
    with provider.write() as scope:
        service = ProjectRepositoryBindingService(scope.repositories, roots)
        service.register(binding)
        service.activate(
            binding.binding_id,
            actor_ref=args.operator_ref,
            activated_at=args.activated_at,
        )
        active = tuple(scope.repositories.project_repository_bindings.list_active())
    inventory = _write_inventory(settings, active)
    return {
        "operation": "initialize_binding",
        "binding_id": binding.binding_id,
        "binding_version": binding.binding_version,
        "base_commit": binding.default_base_commit,
        "inventory_digest": inventory["canonical_digest"],
    }


def _activate_binding(args: argparse.Namespace) -> dict[str, Any]:
    settings = _repository_settings()
    roots = _roots(settings)
    provider = SQLiteRepositoryProvider(str(args.database_path))
    with provider.write() as scope:
        service = ProjectRepositoryBindingService(scope.repositories, roots)
        binding = service.activate(
            args.binding_id,
            actor_ref=args.operator_ref,
            activated_at=args.activated_at,
        )
        active = tuple(scope.repositories.project_repository_bindings.list_active())
    inventory = _write_inventory(settings, active)
    return {
        "operation": "activate_binding",
        "binding_id": binding.binding_id,
        "binding_version": binding.binding_version,
        "inventory_digest": inventory["canonical_digest"],
    }


def _map_session(args: argparse.Namespace) -> dict[str, Any]:
    settings = _repository_settings()
    provider = SQLiteRepositoryProvider(str(args.database_path))
    with provider.write() as scope:
        service = ProjectRepositoryBindingService(scope.repositories, _roots(settings))
        resolved, receipt = service.map_legacy_session(
            session_id=args.session_id,
            binding_id=args.binding_id,
            binding_version=args.binding_version,
            exact_base_commit=args.exact_base_commit,
            operator_ref=args.operator_ref,
            mapping_reason=args.mapping_reason,
            mapped_at=args.mapped_at,
            receipt_id=args.receipt_id,
        )
    return {
        "operation": "map_session",
        "pin": resolved.pin.to_dict(),
        "receipt": receipt,
    }


def _retire_binding(args: argparse.Namespace) -> dict[str, Any]:
    settings = _repository_settings()
    provider = SQLiteRepositoryProvider(str(args.database_path))
    with provider.write() as scope:
        receipt = ProjectRepositoryBindingService(
            scope.repositories,
            _roots(settings),
        ).retire_binding(
            args.binding_id,
            retired_at=args.retired_at,
            retired_by=args.operator_ref,
            receipt_id=args.receipt_id,
        )
        active = tuple(scope.repositories.project_repository_bindings.list_active())
    _write_inventory(settings, active)
    return {"operation": "retire_binding", "receipt": receipt}


def _preflight(args: argparse.Namespace) -> dict[str, Any]:
    settings = _repository_settings()
    provider = SQLiteRepositoryProvider(str(args.database_path))
    return preflight_repository_service(
        settings=settings,
        provider=provider,
        roots=_roots(settings),
    ).to_dict()


def _read_only_audit(args: argparse.Namespace) -> dict[str, Any]:
    path = args.database_path.resolve(strict=True)
    with sqlite3.connect(
        f"file:{path.as_posix()}?mode=ro",
        uri=True,
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if user_version != CURRENT_SQLITE_SCHEMA_VERSION:
            raise RuntimeError(
                f"control-plane schema is {user_version}, expected "
                f"{CURRENT_SQLITE_SCHEMA_VERSION}"
            )
        where = "" if args.binding_id is None else "WHERE binding.binding_id = ?"
        parameters = () if args.binding_id is None else (args.binding_id,)
        rows = connection.execute(
            f"""
            SELECT binding.project_id, binding.binding_id, binding.binding_version,
                   binding.repository_id, binding.default_base_commit,
                   binding.canonical_digest,
                   CASE
                     WHEN retirement.receipt_id IS NOT NULL THEN 'retired'
                     WHEN active.binding_id IS NOT NULL THEN 'active'
                     ELSE 'registered'
                   END AS lifecycle_status,
                   (SELECT COUNT(*) FROM session_repository_binding_pins AS pin
                    WHERE pin.binding_id = binding.binding_id
                      AND pin.binding_version = binding.binding_version)
                       AS session_pin_count,
                   (SELECT COUNT(*) FROM repository_binding_mapping_receipts AS mapping
                    WHERE mapping.binding_id = binding.binding_id
                      AND mapping.binding_version = binding.binding_version)
                       AS mapping_receipt_count,
                   (SELECT COUNT(*) FROM repository_credential_issuance_records AS credential
                    WHERE credential.binding_id = binding.binding_id
                      AND credential.binding_version = binding.binding_version)
                       AS credential_record_count,
                   (SELECT COUNT(*) FROM repository_private_namespace_records AS namespace
                    WHERE namespace.binding_id = binding.binding_id
                      AND namespace.binding_version = binding.binding_version)
                       AS private_namespace_count
            FROM project_repository_binding_versions AS binding
            LEFT JOIN project_repository_active_bindings AS active
              ON active.project_id = binding.project_id
             AND active.binding_id = binding.binding_id
             AND active.binding_version = binding.binding_version
            LEFT JOIN project_repository_binding_retirement_receipts AS retirement
              ON retirement.project_id = binding.project_id
             AND retirement.binding_id = binding.binding_id
             AND retirement.binding_version = binding.binding_version
            {where}
            ORDER BY binding.project_id, binding.binding_version
            """,
            parameters,
        ).fetchall()
        if args.binding_id is not None and not rows:
            raise RuntimeError(f"repository binding {args.binding_id!r} does not exist")
        query_only = bool(connection.execute("PRAGMA query_only").fetchone()[0])
    return {
        "schema_version": "repository_binding_read_only_audit@1",
        "database_identity_digest": (
            f"sha256:{hashlib.sha256(str(path).encode()).hexdigest()}"
        ),
        "schema_version_number": user_version,
        "bindings": [dict(row) for row in rows],
        "query_only": query_only,
    }


def _rehearse_restore(args: argparse.Namespace) -> dict[str, Any]:
    settings = _repository_settings()
    return rehearse_repository_service_restore(
        settings=settings,
        database_path=args.database_path,
        boundary=RepositoryRootBoundary.production(
            host_checkout=Path(__file__).resolve().parents[4],
            process_cwd=Path.cwd(),
        ),
        receipt_id=args.receipt_id,
        created_at=args.created_at,
        created_by=args.operator_ref,
    )


def _serve(args: argparse.Namespace) -> None:
    settings = _repository_settings()
    provider = SQLiteRepositoryProvider(str(args.database_path))
    application = create_repository_transport_app(
        RepositoryTransportDependencies(
            repository_provider=provider,
            settings=settings,
            root_boundary=RepositoryRootBoundary.production(
                host_checkout=Path(__file__).resolve().parents[4],
                process_cwd=Path.cwd(),
            ),
        )
    )
    parsed = urlsplit(settings.https_origin)
    port = args.port or parsed.port or 443
    uvicorn.run(
        application,
        host=args.bind_host,
        port=port,
        ssl_certfile=str(settings.tls_certificate_file),
        ssl_keyfile=str(settings.tls_private_key_file),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate the Host-owned OpenZyme Git/LFS repository service."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_database(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--database-path",
            type=_absolute_database_path,
            required=True,
        )

    preflight = subparsers.add_parser("preflight")
    add_database(preflight)

    audit = subparsers.add_parser("audit")
    audit.add_argument(
        "--database-path",
        type=_absolute_existing_path,
        required=True,
    )
    audit.add_argument("--binding-id")

    rehearsal = subparsers.add_parser("rehearse-restore")
    add_database(rehearsal)
    rehearsal.add_argument("--receipt-id", required=True)
    rehearsal.add_argument("--created-at", required=True)
    rehearsal.add_argument("--operator-ref", required=True)

    initialize = subparsers.add_parser("initialize-binding")
    add_database(initialize)
    initialize.add_argument(
        "--binding-file",
        type=_absolute_existing_path,
        required=True,
    )
    initialize.add_argument(
        "--source-repository",
        type=_absolute_existing_path,
        required=True,
    )
    initialize.add_argument("--source-commit", required=True)
    initialize.add_argument("--operator-ref", required=True)
    initialize.add_argument("--activated-at", required=True)

    activate = subparsers.add_parser("activate-binding")
    add_database(activate)
    activate.add_argument("--binding-id", required=True)
    activate.add_argument("--operator-ref", required=True)
    activate.add_argument("--activated-at", required=True)

    mapping = subparsers.add_parser("map-session")
    add_database(mapping)
    mapping.add_argument("--session-id", required=True)
    mapping.add_argument("--binding-id", required=True)
    mapping.add_argument("--binding-version", type=int, required=True)
    mapping.add_argument("--exact-base-commit", required=True)
    mapping.add_argument("--operator-ref", required=True)
    mapping.add_argument("--mapping-reason", required=True)
    mapping.add_argument("--mapped-at", required=True)
    mapping.add_argument("--receipt-id", required=True)

    retire = subparsers.add_parser("retire-binding")
    add_database(retire)
    retire.add_argument("--binding-id", required=True)
    retire.add_argument("--operator-ref", required=True)
    retire.add_argument("--retired-at", required=True)
    retire.add_argument("--receipt-id", required=True)

    serve = subparsers.add_parser("serve")
    add_database(serve)
    serve.add_argument("--bind-host", default="127.0.0.1")
    serve.add_argument("--port", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        _serve(args)
        return 0
    operations = {
        "preflight": _preflight,
        "audit": _read_only_audit,
        "rehearse-restore": _rehearse_restore,
        "initialize-binding": _initialize_binding,
        "activate-binding": _activate_binding,
        "map-session": _map_session,
        "retire-binding": _retire_binding,
    }
    result = operations[args.command](args)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
