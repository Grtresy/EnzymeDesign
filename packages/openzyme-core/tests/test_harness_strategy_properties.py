from __future__ import annotations
# ruff: noqa: E402

import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
import pytest

from scripts.test_gate.hypothesis_storage import configure_hypothesis_storage

from openzyme_core import CoreRepositories
from openzyme_core import HarnessInput
from openzyme_core import HarnessStatus
from openzyme_core import HarnessStep
from openzyme_core import ToolInvocation
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import run_agent_harness_loop
from openzyme_domain import Session


configure_hypothesis_storage(repo_root=REPOSITORY_ROOT)
_ACTION_SEQUENCES = st.lists(
    st.sampled_from(("public_read", "safe_rejection")),
    min_size=0,
    max_size=8,
)


def test_hypothesis_storage_is_checkout_external() -> None:
    storage = Path(os.environ["HYPOTHESIS_STORAGE_DIRECTORY"])

    assert storage.is_absolute()
    with pytest.raises(ValueError):
        storage.resolve(strict=False).relative_to(REPOSITORY_ROOT)


@dataclass(slots=True)
class _OrdinaryTraceDriver:
    actions: tuple[str, ...]
    offset: int = 0

    def plan(self, context, harness_input, tool_results):  # type: ignore[no-untyped-def]
        del context, harness_input, tool_results
        if self.offset >= len(self.actions):
            return HarnessStep(assistant_message="Observed canonical state.")
        action = self.actions[self.offset]
        self.offset += 1
        if action == "public_read":
            invocation = ToolInvocation(
                call_id=f"read-{self.offset}",
                tool_name="task.list",
                arguments={},
            )
        else:
            invocation = ToolInvocation(
                call_id=f"reject-{self.offset}",
                tool_name="failure.get",
                arguments={},
            )
        return HarnessStep(tool_invocations=(invocation,))


def _run(actions: tuple[str, ...]) -> tuple[HarnessStatus, int, int, int]:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create(
        "session_strategy_property",
        "project_strategy_property",
        "Strategy-neutral property",
        "Observe ordinary action transformations.",
    )
    repositories.sessions.save(session)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            message="Inspect the world and stop.",
            max_steps=len(actions) + 1,
        ),
        driver=_OrdinaryTraceDriver(actions),
    )
    return (
        result.status,
        len(repositories.tasks.list_by_session(session.session_id)),
        len(repositories.approvals.list_by_session(session.session_id)),
        len(repositories.scientific_attempts.list_by_session(session.session_id)),
    )


@settings(max_examples=32, deadline=None, database=None)
@given(_ACTION_SEQUENCES)
def test_ordinary_read_and_safe_rejection_permutations_preserve_business_state(
    actions: list[str],
) -> None:
    baseline = tuple(actions)
    transformed = tuple(reversed(actions)) + ("public_read",)

    assert _run(baseline) == (HarnessStatus.COMPLETED, 0, 0, 0)
    assert _run(transformed) == (HarnessStatus.COMPLETED, 0, 0, 0)


@settings(max_examples=24, deadline=None, database=None)
@given(_ACTION_SEQUENCES.filter(bool))
def test_bounded_turn_exhaustion_never_invents_business_terminal(
    actions: list[str],
) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create(
        "session_bounded_property",
        "project_bounded_property",
        "Bounded property",
        "Keep runtime bounds separate from business state.",
    )
    repositories.sessions.save(session)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, max_steps=len(actions)),
        driver=_OrdinaryTraceDriver(tuple(actions)),
    )

    assert result.status is HarnessStatus.MAX_STEPS_EXCEEDED
    assert repositories.tasks.list_by_session(session.session_id) == []
    assert repositories.scientific_attempts.list_by_session(session.session_id) == []
