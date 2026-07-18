from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_runtime import PodmanContainerLease


def test_container_lease_refuses_unsafe_cidfile_cleanup(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces"
    sandbox_root = workspace_root / "sw_unsafe"
    sandbox_root.mkdir(parents=True)
    lease = PodmanContainerLease.create(
        podman_binary="podman",
        workspace_root=workspace_root,
        sandbox_root=sandbox_root,
        run_id="podman_unsafe_cid",
    )
    lease.cidfile_path.write_text("a" * 64 + "\n", encoding="ascii")
    second_link = tmp_path / "second-link.cid"
    os.link(lease.cidfile_path, second_link)

    assert lease._remove_retired_cidfile() is False
    assert lease.cidfile_path.exists()
    assert second_link.exists()

    second_link.unlink()
    assert lease._remove_retired_cidfile() is True
    assert lease.cidfile_path.exists() is False


def test_container_lease_retires_exact_cid_after_transient_faults_and_name_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    sandbox_root = workspace_root / "sw_001"
    sandbox_root.mkdir(parents=True)
    lease = PodmanContainerLease.create(
        podman_binary="podman",
        workspace_root=workspace_root,
        sandbox_root=sandbox_root,
        run_id="podman_0123456789ab",
    )
    container_id = "c" * 64
    lease.cidfile_path.write_text(container_id + "\n", encoding="ascii")
    removed = False
    retirement_error_injected = False
    cid_read_error_injected = False
    cid_unlink_error_injected = False
    calls: list[list[str]] = []

    real_os_read = os.read
    real_path_unlink = Path.unlink

    def transient_cid_read(descriptor: int, length: int) -> bytes:
        nonlocal cid_read_error_injected
        if not cid_read_error_injected:
            cid_read_error_injected = True
            raise OSError("transient cid read failure")
        return real_os_read(descriptor, length)

    def transient_cid_unlink(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal cid_unlink_error_injected
        if path == lease.cidfile_path and not cid_unlink_error_injected:
            cid_unlink_error_injected = True
            raise OSError("transient cid unlink failure")
        real_path_unlink(path, *args, **kwargs)

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        nonlocal removed, retirement_error_injected
        del kwargs
        command = list(command)
        calls.append(command)
        if command[1:3] == ["container", "exists"]:
            if not retirement_error_injected:
                retirement_error_injected = True
                raise RuntimeError("transient podman decode failure")
            reference = command[-1]
            return SimpleNamespace(
                returncode=(
                    1 if reference == lease.container_name or removed else 0
                ),
                stdout="",
                stderr="",
            )
        if command[1:3] == ["container", "inspect"]:
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    f"{container_id} {lease.run_id} "
                    f"{lease.sandbox_root_digest}\n"
                ).encode("ascii"),
                stderr=b"",
            )
        if command[1] == "rm":
            removed = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("openzyme_runtime.podman_lifecycle.subprocess.run", fake_run)
    monkeypatch.setattr("openzyme_runtime.podman_lifecycle.os.read", transient_cid_read)
    monkeypatch.setattr(
        "openzyme_runtime.podman_lifecycle.Path.unlink",
        transient_cid_unlink,
    )

    lease.retire()

    kill_index = next(index for index, command in enumerate(calls) if command[1] == "kill")
    wait_index = next(index for index, command in enumerate(calls) if command[1] == "wait")
    rm_index = next(index for index, command in enumerate(calls) if command[1] == "rm")
    assert calls[kill_index] == ["podman", "kill", container_id]
    assert calls[wait_index] == ["podman", "wait", container_id]
    assert calls[rm_index] == [
        "podman",
        "rm",
        "--force",
        "--time",
        "0",
        "--ignore",
        container_id,
    ]
    assert kill_index < wait_index < rm_index
    exists_references = [
        command[-1]
        for command in calls
        if command[1:3] == ["container", "exists"]
    ]
    assert container_id in exists_references
    assert lease.container_name in exists_references
    inspect = next(
        command for command in calls if command[1:3] == ["container", "inspect"]
    )
    assert inspect[-1] == container_id
    assert cid_read_error_injected is True
    assert cid_unlink_error_injected is True
    assert retirement_error_injected is True
    assert lease.cidfile_path.exists() is False
