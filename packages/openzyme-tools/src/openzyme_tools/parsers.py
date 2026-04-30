from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactParseResult:
    parser_status: str
    findings: dict[str, Any]
    summary: str | None = None


def parse_fpocket_artifacts(artifact_refs: list[dict[str, Any]]) -> ArtifactParseResult:
    info_path = _find_artifact_path(artifact_refs, "target_info.txt")
    if info_path is None:
        return ArtifactParseResult(
            parser_status="missing_artifact",
            findings={},
            summary="fpocket completed, but no target_info.txt artifact was available for parsing.",
        )

    try:
        text = info_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ArtifactParseResult(
            parser_status="read_error",
            findings={"parser_error": str(exc)},
            summary="fpocket completed, but the pocket descriptor artifact could not be read.",
        )

    pockets = _parse_fpocket_info(text)
    if not pockets:
        return ArtifactParseResult(
            parser_status="unparsed",
            findings={"parsed_artifact": str(info_path)},
            summary="fpocket completed, but no pocket descriptors could be parsed.",
        )

    top_pocket = pockets[0]
    findings = {
        "pockets_found": len(pockets),
        "top_pocket": top_pocket,
        "pockets": pockets,
        "parsed_artifact": str(info_path),
    }
    summary = (
        f"fpocket found {len(pockets)} pocket(s); top pocket score "
        f"{top_pocket.get('score', 'unknown')}."
    )
    return ArtifactParseResult(
        parser_status="parsed",
        findings=findings,
        summary=summary,
    )


def parse_vina_artifacts(artifact_refs: list[dict[str, Any]]) -> ArtifactParseResult:
    log_path = _find_artifact_path(artifact_refs, "vina.log")
    if log_path is None:
        return ArtifactParseResult(
            parser_status="missing_artifact",
            findings={},
            summary="vina completed, but no vina.log artifact was available for parsing.",
        )

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ArtifactParseResult(
            parser_status="read_error",
            findings={"parser_error": str(exc)},
            summary="vina completed, but the docking log artifact could not be read.",
        )

    modes = _parse_vina_modes(text)
    if not modes:
        return ArtifactParseResult(
            parser_status="unparsed",
            findings={"parsed_artifact": str(log_path)},
            summary="vina completed, but no scored docking modes could be parsed.",
        )

    best_mode = modes[0]
    best_affinity = best_mode["affinity_kcal_mol"]
    findings = {
        "best_affinity": best_affinity,
        "best_mode": best_mode,
        "mode_count": len(modes),
        "modes": modes,
        "parsed_artifact": str(log_path),
    }
    summary = f"vina completed with best affinity {best_affinity:.2f} kcal/mol."
    return ArtifactParseResult(
        parser_status="parsed",
        findings=findings,
        summary=summary,
    )


def _find_artifact_path(
    artifact_refs: list[dict[str, Any]], filename: str
) -> Path | None:
    candidate_paths: list[Path] = []
    for artifact_ref in artifact_refs:
        for key in ("local_path", "storage_uri", "path", "uri"):
            value = artifact_ref.get(key)
            if not isinstance(value, str) or not value:
                continue
            if "://" in value:
                continue
            candidate_paths.append(Path(value))

    for candidate in candidate_paths:
        if candidate.is_file() and candidate.name == filename:
            return candidate
        if candidate.is_dir():
            direct = candidate / filename
            if direct.is_file():
                return direct
            matches = sorted(candidate.rglob(filename))
            if matches:
                return matches[0]
    return None


def _parse_fpocket_info(text: str) -> list[dict[str, Any]]:
    pockets: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in text.splitlines():
        pocket_match = re.match(r"^\s*Pocket\s+(\d+)\s*:", line)
        if pocket_match:
            if current is not None:
                pockets.append(current)
            current = {"pocket_id": int(pocket_match.group(1))}
            continue
        if current is None or ":" not in line:
            continue
        label, raw_value = line.split(":", 1)
        key = _normalise_fpocket_key(label)
        value = _parse_number(raw_value)
        if key:
            current[key] = value

    if current is not None:
        pockets.append(current)
    return pockets


def _normalise_fpocket_key(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    aliases = {
        "score": "score",
        "druggability_score": "druggability_score",
        "number_of_alpha_spheres": "alpha_sphere_count",
        "volume": "volume",
        "total_sasa": "total_sasa",
        "polar_sasa": "polar_sasa",
        "apolar_sasa": "apolar_sasa",
    }
    return aliases.get(key, key)


def _parse_vina_modes(text: str) -> list[dict[str, Any]]:
    modes: list[dict[str, Any]] = []
    mode_line = re.compile(
        r"^\s*(?P<mode>\d+)\s+"
        r"(?P<affinity>[-+]?\d+(?:\.\d+)?)\s+"
        r"(?P<rmsd_lb>[-+]?\d+(?:\.\d+)?)\s+"
        r"(?P<rmsd_ub>[-+]?\d+(?:\.\d+)?)\s*$"
    )
    for line in text.splitlines():
        match = mode_line.match(line)
        if match is None:
            continue
        modes.append(
            {
                "mode": int(match.group("mode")),
                "affinity_kcal_mol": float(match.group("affinity")),
                "rmsd_lb": float(match.group("rmsd_lb")),
                "rmsd_ub": float(match.group("rmsd_ub")),
            }
        )
    return modes


def _parse_number(raw_value: str) -> float | int | str:
    value = raw_value.strip()
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer():
        return int(number)
    return number


__all__ = [
    "ArtifactParseResult",
    "parse_fpocket_artifacts",
    "parse_vina_artifacts",
]
