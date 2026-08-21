from __future__ import annotations

import os
from pathlib import Path

import pytest

from openzyme_process_podman import PodmanAdapterConfiguration
from openzyme_process_podman import preflight_podman_adapter


def _configuration(binary: Path) -> PodmanAdapterConfiguration:
    return PodmanAdapterConfiguration(
        podman_binary=str(binary),
        deployment_network="openzyme-local",
        runtime_uid=10_001,
        runtime_gid=10_001,
        image_identity="registry.invalid/openzyme@sha256:" + "a" * 64,
    )


def test_preflight_binds_exact_binary_without_running_it(tmp_path: Path) -> None:
    binary = tmp_path / "podman"
    binary.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    binary.chmod(0o700)

    receipt = preflight_podman_adapter(_configuration(binary))

    assert receipt.ready is True
    assert receipt.subprocess_probe_performed is False
    assert receipt.network_probe_performed is False
    assert receipt.binary_identity_digest.startswith("sha256:")


def test_preflight_fails_closed_for_missing_or_non_executable_binary(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(RuntimeError, match="cannot be observed"):
        preflight_podman_adapter(_configuration(missing))

    non_executable = tmp_path / "podman"
    non_executable.write_text("not executable", encoding="utf-8")
    non_executable.chmod(0o600)
    assert not os.access(non_executable, os.X_OK)
    with pytest.raises(RuntimeError, match="not a regular executable"):
        preflight_podman_adapter(_configuration(non_executable))


def test_configuration_rejects_unknown_fields_and_ambient_binary_names() -> None:
    value = {
        "schema_version": "openzyme_podman_adapter_configuration@1",
        "podman_binary": "/usr/bin/podman",
        "deployment_network": "openzyme-local",
        "runtime_uid": 10_001,
        "runtime_gid": 10_001,
        "image_identity": "image@sha256:" + "a" * 64,
    }
    assert PodmanAdapterConfiguration.from_mapping(value).podman_binary == (
        "/usr/bin/podman"
    )
    with pytest.raises(ValueError, match="closed"):
        PodmanAdapterConfiguration.from_mapping({**value, "fallback": "docker"})
    with pytest.raises(ValueError, match="absolute"):
        PodmanAdapterConfiguration.from_mapping({**value, "podman_binary": "podman"})
