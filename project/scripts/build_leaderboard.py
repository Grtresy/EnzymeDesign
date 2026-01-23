#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import pandas as pd

from utils.io import read_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build leaderboard")
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows: List[dict] = []
    for path_str in args.inputs:
        path = Path(path_str)
        data = read_json(path)
        rows.append(
            {
                "variant_id": data["variant_id"],
                "final_score": data["final_score"],
                "needs_review": data["needs_review"],
            }
        )
    df = pd.DataFrame(rows).sort_values(by="final_score", ascending=False)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

