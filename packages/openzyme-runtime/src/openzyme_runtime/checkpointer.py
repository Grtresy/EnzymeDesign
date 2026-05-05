from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import Any
from typing import Iterator


class MissingLangGraphPostgresDependencyError(RuntimeError):
    """Raised when durable Postgres checkpointing is configured without the extra package."""


@dataclass(frozen=True, slots=True)
class PostgresCheckpointerConfig:
    conn_string: str
    setup_on_bootstrap: bool = True


def _load_postgres_module() -> ModuleType:
    try:
        return import_module("langgraph.checkpoint.postgres")
    except ModuleNotFoundError as exc:
        msg = (
            "langgraph.checkpoint.postgres is unavailable. "
            "Install the 'openzyme-runtime[postgres]' extra for durable checkpointer support."
        )
        raise MissingLangGraphPostgresDependencyError(msg) from exc


def _load_postgres_saver_class() -> type[Any]:
    module = _load_postgres_module()
    try:
        return getattr(module, "PostgresSaver")
    except AttributeError as exc:
        msg = "langgraph.checkpoint.postgres.PostgresSaver is unavailable"
        raise MissingLangGraphPostgresDependencyError(msg) from exc


@dataclass(frozen=True, slots=True)
class PostgresCheckpointerFactory:
    config: PostgresCheckpointerConfig

    @contextmanager
    def open(self) -> Iterator[Any]:
        saver_class = _load_postgres_saver_class()
        with saver_class.from_conn_string(self.config.conn_string) as checkpointer:
            if self.config.setup_on_bootstrap:
                checkpointer.setup()
            yield checkpointer
