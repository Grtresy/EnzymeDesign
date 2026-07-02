from __future__ import annotations

from typing import Any


class RepoBackedHpcCatalogProvider:
    """Compatibility shim for the catalog provider now owned by openzyme-tools."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        from openzyme_tools import RepoBackedHpcCatalogProvider as ToolsRepoBackedHpcCatalogProvider

        return ToolsRepoBackedHpcCatalogProvider(*args, **kwargs)


__all__ = ["RepoBackedHpcCatalogProvider"]
