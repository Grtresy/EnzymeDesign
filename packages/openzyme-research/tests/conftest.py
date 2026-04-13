from __future__ import annotations

import pytest

from openzyme_runtime import live_tavily_skip_reason
from openzyme_runtime import load_current_settings


def pytest_runtest_setup(item: pytest.Item) -> None:
    if not item.get_closest_marker("live_tavily"):
        return
    reason = live_tavily_skip_reason(load_current_settings())
    if reason is not None:
        pytest.skip(reason)
