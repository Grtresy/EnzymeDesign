from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess

import uvicorn

from openzyme_runtime import REPO_ROOT

from .app import HostApiDependencies
from .app import create_app
from .foundation import build_configured_foundation
from .foundation import build_local_eval_foundation
from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations as apply_v3_sqlite_migrations
from openzyme_core import connect_sqlite as connect_v3_sqlite
from openzyme_core import sandbox_image_record


DEFAULT_SANDBOX_IMAGE_REF = "localhost/openzyme-pipeline-sandbox:dev"


def _default_ui_dist() -> Path:
    return REPO_ROOT / "apps" / "openzyme-web-ui" / "dist"


def _default_sqlite_db() -> Path:
    return Path("/tmp/openzyme-web-ui-runtime.sqlite3")


def _default_v3_sqlite_db() -> Path:
    return Path("/tmp/openzyme-web-ui-v3.sqlite3")


def _build_v3_repositories(sqlite_db_path: Path) -> CoreRepositories:
    sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_v3_sqlite(str(sqlite_db_path))
    apply_v3_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _register_existing_sandbox_image(
    repositories: CoreRepositories,
    *,
    image_ref: str = DEFAULT_SANDBOX_IMAGE_REF,
    podman_binary: str = "podman",
) -> None:
    if shutil.which(podman_binary) is None:
        return
    try:
        exists = subprocess.run(
            [podman_binary, "image", "exists", image_ref],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if exists.returncode != 0:
        return
    try:
        inspect = subprocess.run(
            [podman_binary, "image", "inspect", image_ref, "--format", "{{.Id}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    image_digest = inspect.stdout.strip()
    if inspect.returncode != 0 or not image_digest:
        return
    if not image_digest.startswith("sha256:"):
        image_digest = f"sha256:{image_digest}"
    repositories.sandbox_images.save(
        sandbox_image_record(image_ref=image_ref, image_digest=image_digest)
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve the V3 Web UI mounted on the Host API for local manual testing."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--ui-dist",
        type=Path,
        default=_default_ui_dist(),
        help="Built web UI dist directory. Run npm run build in apps/openzyme-web-ui first.",
    )
    parser.add_argument(
        "--sqlite-db",
        type=Path,
        default=_default_sqlite_db(),
        help="SQLite path for legacy/runtime local manual testing.",
    )
    parser.add_argument(
        "--v3-sqlite-db",
        type=Path,
        default=_default_v3_sqlite_db(),
        help="SQLite path for V3 control-plane local manual testing.",
    )
    parser.add_argument(
        "--configured",
        action="store_true",
        help="Use configured runtime adapters from environment instead of deterministic local adapters.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ui_dist = args.ui_dist.resolve()
    if not ui_dist.exists():
        raise SystemExit(
            f"UI dist directory does not exist: {ui_dist}. "
            "Run `cd apps/openzyme-web-ui && npm run build` first."
        )
    foundation_builder = (
        build_configured_foundation if args.configured else build_local_eval_foundation
    )
    foundation = foundation_builder(sqlite_db_path=args.sqlite_db)
    v3_repositories = _build_v3_repositories(args.v3_sqlite_db)
    if args.configured:
        _register_existing_sandbox_image(v3_repositories)
    app = create_app(
        HostApiDependencies(
            foundation=foundation,
            v3_repositories=v3_repositories,
        ),
        ui_dist_dir=ui_dist,
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
