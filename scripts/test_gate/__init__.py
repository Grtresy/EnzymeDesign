"""Repository-local test-gate operator plane.

This package intentionally lives under ``scripts``.  It must not be imported by
OpenZyme product packages or used as product control-plane state.
"""

from .config import (
    CONFIG_SCHEMA_ID,
    ConfigError,
    TestGateConfig,
    load_config,
    validate_dispatch_profile,
)
from .model import EvidenceModelError
from .runner import TestGateRunnerError
from .source import SourceIdentityError

__all__ = [
    "CONFIG_SCHEMA_ID",
    "ConfigError",
    "EvidenceModelError",
    "SourceIdentityError",
    "TestGateConfig",
    "TestGateRunnerError",
    "load_config",
    "validate_dispatch_profile",
]
