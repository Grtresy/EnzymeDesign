from __future__ import annotations

import importlib.metadata

import pytest

from openzyme_science import ScientificAttemptLifecyclePhase
from openzyme_science import ScientificAttemptScope
from openzyme_science import ScientificAttemptStatus
from openzyme_science import ScientificFileStorage
from openzyme_science import normalize_scientific_path


def test_science_wheel_owns_scientific_vocabulary_without_implementation_deps() -> None:
    requirements = importlib.metadata.requires("openzyme-science") or []
    runtime_requirements = sorted(
        requirement for requirement in requirements if "extra ==" not in requirement
    )

    assert runtime_requirements == ["openzyme-contracts", "openzyme-extension-spi"]
    assert ScientificAttemptScope.FORMAL.value == "formal"
    assert ScientificAttemptStatus.CLOSED.is_terminal is True
    assert ScientificAttemptLifecyclePhase.OPEN.accepts_scientific_mutation is True
    assert ScientificFileStorage.GIT_LFS.value == "git_lfs"


@pytest.mark.parametrize(
    "path",
    (
        "/absolute/result.json",
        "../other/result.json",
        ".git/config",
        "results\\result.json",
    ),
)
def test_scientific_paths_remain_revision_relative(path: str) -> None:
    with pytest.raises(ValueError):
        normalize_scientific_path(path)


def test_scientific_path_normalization_preserves_valid_revision_path() -> None:
    assert normalize_scientific_path("results/run-01/summary.json") == (
        "results/run-01/summary.json"
    )
