"""mcp-hpc-tool-contracts package."""

from .registry import ADAPTER_IDS, list_adapters
from .service import compile_adapter, run_adapter

__all__ = ["ADAPTER_IDS", "compile_adapter", "list_adapters", "run_adapter"]
