from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest


def test_build_leaderboard_creates_sorted_csv(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("pandas")
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    import build_leaderboard

    score_a = tmp_path / "score_a.json"
    score_b = tmp_path / "score_b.json"
    score_a.write_text(
        "{\"variant_id\": \"a\", \"final_score\": 0.2, \"needs_review\": false}",
        encoding="utf-8",
    )
    score_b.write_text(
        "{\"variant_id\": \"b\", \"final_score\": 0.8, \"needs_review\": true}",
        encoding="utf-8",
    )

    output_path = tmp_path / "leaderboard.csv"
    argv = [
        "build_leaderboard.py",
        "--inputs",
        str(score_a),
        str(score_b),
        "--output",
        str(output_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)

    assert build_leaderboard.main() == 0

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert [row["variant_id"] for row in rows] == ["b", "a"]
