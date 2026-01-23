from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path


def test_real_mode_runs_hhblits(tmp_path: Path, monkeypatch) -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    from tools import hhblits

    db_path = tmp_path / "hhblits_db"
    db_path.write_text("db", encoding="utf-8")

    hhblits_script = tmp_path / "hhblits"
    hhblits_script.write_text(
        textwrap.dedent(
            f"""\
#!/usr/bin/env python3
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("-i", required=True)
parser.add_argument("-d", required=True)
parser.add_argument("-oa3m", required=True)
parser.add_argument("-o", required=True)
parser.add_argument("-e", required=True)
parser.add_argument("-n", required=True)
parser.add_argument("-maxseq")
parser.add_argument("-cpu")
args = parser.parse_args()

if args.d != r"{db_path}":
    raise SystemExit(2)
if args.e != "0.001":
    raise SystemExit(3)
if args.n != "2":
    raise SystemExit(4)
if args.maxseq != "5000":
    raise SystemExit(5)
if args.cpu != "8":
    raise SystemExit(6)

Path(args.oa3m).parent.mkdir(parents=True, exist_ok=True)
Path(args.oa3m).write_text(">query\\nAAAA\\n>hit\\nAAAA\\n", encoding="utf-8")
Path(args.o).write_text("HHBLITS", encoding="utf-8")
"""
        ),
        encoding="utf-8",
    )
    hhblits_script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")

    fasta_path = tmp_path / "variant.fasta"
    fasta_path.write_text(">variant\nAAAA\n", encoding="utf-8")
    output_path = tmp_path / "runs" / "target" / "variant" / "outputs" / "features" / "msa.a3m"

    params = {
        "config": {
            "hhblits_db": str(db_path),
            "hhblits": {
                "evalue": 1e-3,
                "num_iterations": 2,
                "maxseq": 5000,
                "cpu": 8,
                "extra_args": [],
            },
        }
    }

    hhblits.run(
        inputs=[fasta_path],
        outputs={"msa": output_path},
        params=params,
        workdir=tmp_path,
        mode="real",
    )

    assert output_path.exists()
    assert output_path.stat().st_size > 0
