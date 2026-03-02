from __future__ import annotations

import pytest

from mcp_hpc_tool_contracts.cluster_profile import AdapterProfile, ClusterProfile
from mcp_hpc_tool_contracts.registry import compile_adapter


def _sif_profile(adapter_id: str) -> ClusterProfile:
    return ClusterProfile(adapters={adapter_id: AdapterProfile(mode="sif")})


def _wrapper_profile(adapter_id: str) -> ClusterProfile:
    return ClusterProfile(adapters={adapter_id: AdapterProfile(mode="wrapper")})


def test_empty_profile_defaults_to_sif(tmp_path) -> None:
    query = tmp_path / "query.fasta"
    query.write_text(">q\nACDE\n", encoding="utf-8")

    compiled = compile_adapter("hhblits", {"query_fasta": str(query)})
    assert compiled.invocation_mode == "sif"
    assert compiled.runspec["command"][0] == "apptainer"


def test_wrapper_profile_selects_wrapper_command(tmp_path) -> None:
    query = tmp_path / "query.fasta"
    query.write_text(">q\nACDE\n", encoding="utf-8")

    compiled = compile_adapter(
        "hhblits",
        {"query_fasta": str(query)},
        profile=_wrapper_profile("hhblits"),
    )
    assert compiled.invocation_mode == "wrapper"
    assert compiled.runspec["command"][0] == "/opt/tools/hhblits"


def test_invalid_mode_raises_value_error(tmp_path) -> None:
    query = tmp_path / "query.fasta"
    query.write_text(">q\nACDE\n", encoding="utf-8")

    bad_profile = ClusterProfile(adapters={"hhblits": AdapterProfile(mode="docker")})
    with pytest.raises(ValueError, match="Invalid invocation mode"):
        compile_adapter("hhblits", {"query_fasta": str(query)}, profile=bad_profile)


def test_cluster_profile_from_toml(tmp_path) -> None:
    toml_text = """
[adapters.fpocket]
mode = "sif"
partition = "3090"
gpus = 0

[adapters.alphafold3]
mode = "wrapper"
partition = "3090"
gpus = 1
"""
    config_file = tmp_path / "cluster.toml"
    config_file.write_text(toml_text, encoding="utf-8")

    profile = ClusterProfile.from_toml(config_file)
    assert profile.mode_for("fpocket") == "sif"
    assert profile.mode_for("alphafold3") == "wrapper"
    assert profile.mode_for("unknown_tool") == "sif"  # default

    overrides = profile.resource_overrides_for("alphafold3")
    assert overrides["partition"] == "3090"
    assert overrides["gpus"] == 1
