from __future__ import annotations

from typing import Any

from .client import call
from .hpc import HpcWorkspace


def cdhit(
    *,
    input_fasta: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    identity: float,
    mode: str = "protein",
) -> dict[str, Any]:
    return dict(
        call(
            "bio_tools.cdhit",
            {
                "input_fasta": dict(input_fasta),
                "placement": placement.to_dict(),
                "expected_outputs": list(expected_outputs),
                "identity": identity,
                "mode": mode,
            },
        )
    )


def mafft(
    *,
    input_fasta: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio_tools.mafft",
            {
                "input_fasta": dict(input_fasta),
                "placement": placement.to_dict(),
                "expected_outputs": list(expected_outputs),
                "params": dict(params or {}),
            },
        )
    )


def hmmbuild(
    *,
    alignment: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio_tools.hmmbuild",
            {
                "alignment": dict(alignment),
                "placement": placement.to_dict(),
                "expected_outputs": list(expected_outputs),
                "params": dict(params or {}),
            },
        )
    )


def hmmalign(
    *,
    hmm: dict[str, Any],
    fasta: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio_tools.hmmalign",
            {
                "hmm": dict(hmm),
                "fasta": dict(fasta),
                "placement": placement.to_dict(),
                "expected_outputs": list(expected_outputs),
                "params": dict(params or {}),
            },
        )
    )


def hmmer_search_cli(
    *,
    hmm: dict[str, Any],
    target_fasta: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "bio_tools.hmmer_search_cli",
            {
                "hmm": dict(hmm),
                "target_fasta": dict(target_fasta),
                "placement": placement.to_dict(),
                "expected_outputs": list(expected_outputs),
                "params": dict(params or {}),
            },
        )
    )


__all__ = ["cdhit", "hmmalign", "hmmbuild", "hmmer_search_cli", "mafft"]
