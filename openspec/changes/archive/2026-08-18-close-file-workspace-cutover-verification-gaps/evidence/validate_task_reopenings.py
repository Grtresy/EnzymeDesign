from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
TASK_RE = re.compile(r"^- \[(?P<state>[x ])\] (?P<task>[0-9]+(?:\.[0-9]+)+) ")
EXPECTED_REMEDIATED_TASKS = {
    "supersede-aox-hmm-artifact-cutover": {"4.6"},
    "provision-independent-agent-git-workspaces": {"6.1", "6.4", "7.6"},
    "publish-and-sync-workspace-revisions": {"4.5", "4.8", "7.6"},
    "support-git-lfs-work-products": {"6.4"},
    "migrate-research-report-and-task-handoffs-to-files": {"7.1", "7.4"},
    "provision-isolated-executor-hpc-workspaces": {"7.4"},
    "execute-hpc-jobs-from-workspace-revisions": {"4.5", "6.6", "8.1", "8.4"},
    "migrate-scientific-deliverables-to-files": {"7.4", "8.1", "8.2", "8.5"},
    "replace-sandbox-artifact-boundaries-with-files": {"7.4"},
    "establish-project-repository-bindings": {"7.6"},
    "establish-agent-capability-leases": {"6.6"},
    "cut-over-workspace-public-interfaces": {"8.1", "8.3", "8.6"},
    "migrate-historical-artifacts-to-git-lfs": {"9.6"},
    "remove-artifact-control-plane-and-storage": {
        "7.1",
        "7.2",
        "8.1",
        "8.3",
        "9.1",
        "9.2",
        "9.5",
    },
}
EXPECTED_TOTALS = {
    "supersede-aox-hmm-artifact-cutover": 21,
    "provision-independent-agent-git-workspaces": 45,
    "publish-and-sync-workspace-revisions": 42,
    "support-git-lfs-work-products": 27,
    "migrate-research-report-and-task-handoffs-to-files": 29,
    "provision-isolated-executor-hpc-workspaces": 34,
    "execute-hpc-jobs-from-workspace-revisions": 45,
    "migrate-scientific-deliverables-to-files": 37,
    "replace-sandbox-artifact-boundaries-with-files": 37,
    "establish-project-repository-bindings": 40,
    "establish-agent-capability-leases": 37,
    "cut-over-workspace-public-interfaces": 42,
    "migrate-historical-artifacts-to-git-lfs": 42,
    "remove-artifact-control-plane-and-storage": 51,
}


def validate() -> None:
    for change_id, remediated_tasks in EXPECTED_REMEDIATED_TASKS.items():
        task_path = REPO_ROOT / "openspec" / "changes" / change_id / "tasks.md"
        task_states: dict[str, str] = {}
        task_lines: dict[str, str] = {}
        for line in task_path.read_text(encoding="utf-8").splitlines():
            match = TASK_RE.match(line)
            if match is None:
                continue
            task_id = match.group("task")
            if task_id in task_states:
                raise ValueError(f"{change_id} repeats task {task_id}")
            task_states[task_id] = match.group("state")
            task_lines[task_id] = line
        if len(task_states) != EXPECTED_TOTALS[change_id]:
            raise ValueError(
                f"{change_id} task count changed: expected={EXPECTED_TOTALS[change_id]}, "
                f"observed={len(task_states)}"
            )
        observed_open = {task_id for task_id, state in task_states.items() if state == " "}
        if observed_open:
            raise ValueError(
                f"{change_id} still has incomplete tasks: observed={sorted(observed_open)}"
            )
        for task_id in remediated_tasks:
            if task_states.get(task_id) != "x":
                raise ValueError(f"{change_id} remediated task {task_id} is not complete")
            if "GAP-" not in task_lines[task_id]:
                raise ValueError(f"{change_id} task {task_id} lacks a gap registry link")


if __name__ == "__main__":
    try:
        validate()
    except ValueError as exc:
        print(f"task-reopenings-invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("task-remediation-valid: 14 changes, 529 tasks, 33 reopened gaps reclosed")
