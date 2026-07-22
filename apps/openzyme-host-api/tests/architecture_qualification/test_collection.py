from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationManifestError,
)

from .collection import SCENARIO_MARKER
from .collection import collect_qualification_scenarios


@dataclass
class _FakeItem:
    path: Path
    nodeid: str
    markers: list[SimpleNamespace]
    skip: bool = False
    xfail: bool = False
    parametrized: bool = False

    def __post_init__(self) -> None:
        if self.parametrized:
            self.callspec = object()  # type: ignore[attr-defined]

    def iter_markers(self, *, name: str):  # type: ignore[no-untyped-def]
        if name != SCENARIO_MARKER:
            return iter(())
        return iter(self.markers)

    def get_closest_marker(self, name: str):  # type: ignore[no-untyped-def]
        if name == "skip" and self.skip:
            return object()
        if name == "xfail" and self.xfail:
            return object()
        return None


def _marker(
    *,
    scenario_id: str = "wire-contract.direct-envelope",
    family: str = "wire-contract",
    selections: tuple[str, ...] = ("full", "premerge_subset"),
) -> SimpleNamespace:
    return SimpleNamespace(
        args=(),
        kwargs={
            "family": family,
            "scenario_id": scenario_id,
            "selections": selections,
        },
    )


def _scenario_source(tmp_path: Path) -> tuple[Path, Path, str]:
    repo_root = tmp_path / "repo"
    relative = Path(
        "apps/openzyme-host-api/tests/architecture_qualification/scenarios/"
        "test_wire_contract.py"
    )
    source = repo_root / relative
    source.parent.mkdir(parents=True)
    source.write_text(
        "def test_direct_envelope(driver, collector):\n"
        "    assert driver is not None and collector is not None\n",
        encoding="utf-8",
    )
    return repo_root, source, relative.as_posix()


def test_collection_derives_source_and_keeps_stable_id_separate_from_node_id(
    tmp_path: Path,
) -> None:
    repo_root, source, relative = _scenario_source(tmp_path)
    node_id = f"{relative}::test_direct_envelope"
    item = _FakeItem(path=source, nodeid=node_id, markers=[_marker()])

    collected = collect_qualification_scenarios([item], repo_root=repo_root)

    assert collected[0].scenario_id == "wire-contract.direct-envelope"
    assert collected[0].node_id == node_id
    assert collected[0].source_file == relative
    assert collected[0].selections == ("full", "premerge_subset")


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "skip", "xfail", "parametrized", "open-marker"],
)
def test_collection_rejects_missing_duplicate_skip_xfail_and_open_markers(
    tmp_path: Path,
    mutation: str,
) -> None:
    repo_root, source, relative = _scenario_source(tmp_path)
    markers = [_marker()]
    item = _FakeItem(
        path=source,
        nodeid=f"{relative}::test_direct_envelope",
        markers=markers,
        skip=mutation == "skip",
        xfail=mutation == "xfail",
        parametrized=mutation == "parametrized",
    )
    if mutation == "missing":
        item.markers = []
    elif mutation == "duplicate":
        item.markers.append(_marker())
    elif mutation == "open-marker":
        item.markers[0].kwargs["unknown"] = True

    with pytest.raises(ArchitectureQualificationManifestError):
        collect_qualification_scenarios([item], repo_root=repo_root)


def test_collection_rejects_source_policy_and_marker_outside_scenario_tree(
    tmp_path: Path,
) -> None:
    repo_root, source, relative = _scenario_source(tmp_path)
    source.write_text(
        "from openzyme_host_api.foundation import build_local_eval_foundation\n",
        encoding="utf-8",
    )
    item = _FakeItem(
        path=source,
        nodeid=f"{relative}::test_direct_envelope",
        markers=[_marker()],
    )
    with pytest.raises(ValueError, match="production-only policy"):
        collect_qualification_scenarios([item], repo_root=repo_root)

    outside = repo_root / "apps/openzyme-host-api/tests/test_outside.py"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("def test_outside(): pass\n", encoding="utf-8")
    item = _FakeItem(
        path=outside,
        nodeid="apps/openzyme-host-api/tests/test_outside.py::test_outside",
        markers=[_marker()],
    )
    with pytest.raises(ArchitectureQualificationManifestError, match="outside"):
        collect_qualification_scenarios([item], repo_root=repo_root)
