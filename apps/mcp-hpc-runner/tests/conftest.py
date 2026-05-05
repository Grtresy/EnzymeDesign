from __future__ import annotations

import pytest

from openzyme_runtime import live_hpc_skip_reason
from openzyme_runtime import load_current_settings


def pytest_runtest_setup(item: pytest.Item) -> None:
    if not item.get_closest_marker("live_hpc"):
        return
    reason = live_hpc_skip_reason(load_current_settings())
    if reason is not None:
        pytest.skip(reason)
