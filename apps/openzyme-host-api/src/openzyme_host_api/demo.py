from __future__ import annotations

from pathlib import Path

import uvicorn
from openzyme_graph.supervisor import build_v2_supervisor_graph
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import REPO_ROOT
from openzyme_runtime import get_settings

from .app import HostApiDependencies
from .app import create_app
from .foundation import build_configured_foundation
from .foundation import build_demo_foundation as _build_demo_foundation
from .foundation import build_model_factory_from_env
from .foundation import build_model_factory_from_settings
from .foundation import DemoExecutionAdapter
from .foundation import DemoResearchAdapter
from .foundation import InMemoryCheckpointerFactory


UI_DIST_DIR = REPO_ROOT / "apps" / "openzyme-web-ui" / "dist"
SQLITE_DB_PATH = REPO_ROOT / ".tmp" / "openzyme-demo.sqlite3"


def build_demo_foundation(
    *,
    sqlite_db_path: Path | None = None,
    settings: OpenZymeSettings | None = None,
):
    return _build_demo_foundation(
        sqlite_db_path=sqlite_db_path or SQLITE_DB_PATH,
        settings=settings,
    )


def main() -> None:
    settings = get_settings()
    app = create_app(
        HostApiDependencies(
            foundation=build_demo_foundation(),
            graph_builder=build_v2_supervisor_graph,
        ),
        ui_dist_dir=UI_DIST_DIR if UI_DIST_DIR.exists() else None,
    )
    uvicorn.run(
        app,
        host=settings.host_api.bind_host,
        port=settings.host_api.bind_port,
        log_level="info",
    )


__all__ = [
    "DemoExecutionAdapter",
    "DemoResearchAdapter",
    "InMemoryCheckpointerFactory",
    "SQLITE_DB_PATH",
    "UI_DIST_DIR",
    "build_configured_foundation",
    "build_demo_foundation",
    "build_model_factory_from_env",
    "build_model_factory_from_settings",
    "main",
]


if __name__ == "__main__":
    main()
