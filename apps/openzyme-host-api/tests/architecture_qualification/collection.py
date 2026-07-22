from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

from openzyme_host_api.architecture_qualification import (
    ArchitectureQualificationManifestError,
)
from openzyme_host_api.architecture_qualification import CollectedQualificationScenario
from openzyme_host_api.architecture_qualification import ValidatedInvariantRegistry
from openzyme_host_api.architecture_qualification import ValidatedTestManifest
from openzyme_host_api.architecture_qualification import build_test_manifest

from .safety import validate_qualification_scenario_sources


SCENARIO_MARKER = "architecture_qualification_scenario"
SCENARIO_DIRECTORY = Path(
    "apps/openzyme-host-api/tests/architecture_qualification/scenarios"
)
_MARKER_FIELDS = frozenset({"family", "scenario_id", "selections"})
_STABLE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def _marker_values(marker: Any, *, node_id: str) -> tuple[str, str, tuple[str, ...]]:
    if marker.args or set(marker.kwargs) != _MARKER_FIELDS:
        raise ArchitectureQualificationManifestError(
            f"scenario marker on {node_id!r} is not a closed keyword declaration"
        )
    scenario_id = marker.kwargs["scenario_id"]
    family = marker.kwargs["family"]
    selections = marker.kwargs["selections"]
    if (
        not isinstance(scenario_id, str)
        or _STABLE_ID.fullmatch(scenario_id) is None
        or not isinstance(family, str)
        or _STABLE_ID.fullmatch(family) is None
    ):
        raise ArchitectureQualificationManifestError(
            f"scenario marker on {node_id!r} has an invalid stable identity"
        )
    if not isinstance(selections, (tuple, list)) or any(
        not isinstance(item, str) for item in selections
    ):
        raise ArchitectureQualificationManifestError(
            f"scenario marker on {node_id!r} has invalid selections"
        )
    normalized = tuple(selections)
    if normalized != tuple(sorted(set(normalized))) or "full" not in normalized:
        raise ArchitectureQualificationManifestError(
            f"scenario marker on {node_id!r} selections are not closed"
        )
    return scenario_id, family, normalized


def collect_qualification_scenarios(
    items: Iterable[Any],
    *,
    repo_root: Path,
) -> tuple[CollectedQualificationScenario, ...]:
    root = repo_root.resolve(strict=True)
    collected: list[CollectedQualificationScenario] = []
    for item in items:
        try:
            source = Path(item.path).resolve(strict=True).relative_to(root)
        except (AttributeError, OSError, ValueError) as exc:
            raise ArchitectureQualificationManifestError(
                "pytest item source is outside the canonical repository"
            ) from exc
        source_text = source.as_posix()
        in_scenario_directory = source.is_relative_to(SCENARIO_DIRECTORY)
        markers = list(item.iter_markers(name=SCENARIO_MARKER))
        if not in_scenario_directory:
            if markers:
                raise ArchitectureQualificationManifestError(
                    f"scenario marker is outside {SCENARIO_DIRECTORY.as_posix()!r}"
                )
            continue
        if len(markers) != 1:
            raise ArchitectureQualificationManifestError(
                f"qualification pytest node {item.nodeid!r} must own exactly one marker"
            )
        if hasattr(item, "callspec"):
            raise ArchitectureQualificationManifestError(
                f"qualification pytest node {item.nodeid!r} may not be parametrized"
            )
        if item.get_closest_marker("skip") is not None or item.get_closest_marker(
            "xfail"
        ) is not None:
            raise ArchitectureQualificationManifestError(
                f"qualification pytest node {item.nodeid!r} may not skip or xfail"
            )
        scenario_id, family, selections = _marker_values(
            markers[0], node_id=str(item.nodeid)
        )
        collected.append(
            CollectedQualificationScenario(
                scenario_id=scenario_id,
                family=family,
                node_id=str(item.nodeid),
                source_file=source_text,
                selections=selections,
            )
        )
    source_files = tuple(sorted({item.source_file for item in collected}))
    validate_qualification_scenario_sources(
        repo_root=root,
        source_files=source_files,
    )
    return tuple(sorted(collected, key=lambda item: item.scenario_id))


def close_collection_manifest(
    *,
    registry: ValidatedInvariantRegistry,
    items: Iterable[Any],
    repo_root: Path,
) -> ValidatedTestManifest:
    return build_test_manifest(
        registry,
        collected_scenarios=collect_qualification_scenarios(
            items,
            repo_root=repo_root,
        ),
        repo_root=repo_root,
    )


def collection_payload(
    scenarios: tuple[CollectedQualificationScenario, ...],
) -> Mapping[str, object]:
    return {
        "scenarios": [
            {
                "family": item.family,
                "node_id": item.node_id,
                "scenario_id": item.scenario_id,
                "selections": list(item.selections),
                "source_file": item.source_file,
            }
            for item in scenarios
        ],
        "schema_id": "openzyme_v3_architecture_pytest_collection@1",
    }


__all__ = [
    "SCENARIO_DIRECTORY",
    "SCENARIO_MARKER",
    "close_collection_manifest",
    "collect_qualification_scenarios",
    "collection_payload",
]
