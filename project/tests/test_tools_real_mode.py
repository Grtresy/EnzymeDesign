from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path


def _prepend_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")


def test_real_mode_runs_fpocket(tmp_path: Path, monkeypatch) -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    from tools import fpocket

    fpocket_script = tmp_path / "fpocket"
    fpocket_script.write_text(
        textwrap.dedent(
            """\
#!/usr/bin/env python3
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("-f", required=True)
args = parser.parse_args()

pdb_path = Path(args.f)
out_dir = Path.cwd() / f"{pdb_path.stem}_out" / "pockets"
out_dir.mkdir(parents=True, exist_ok=True)
info = out_dir / "pocket1_info.txt"
info.write_text(
    "Score: 45.6\\n"
    "Volume: 120.0\\n"
    "Center: 1.0 2.0 3.0\\n"
    "Residues: A:5, A:8, A:12\\n",
    encoding="utf-8",
)
"""
        ),
        encoding="utf-8",
    )
    fpocket_script.chmod(0o755)
    _prepend_path(tmp_path, monkeypatch)

    pdb_path = tmp_path / "variant.pdb"
    pdb_path.write_text("ATOM", encoding="utf-8")
    output_path = tmp_path / "outputs" / "pockets.json"

    fpocket.run(
        inputs=[pdb_path],
        outputs={"pockets": output_path},
        params={},
        workdir=tmp_path,
        mode="real",
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["pockets"][0]["pocket_id"] == "pocket-1"
    assert data["pockets"][0]["score"] == 45.6
    assert data["pockets"][0]["center"] == [1.0, 2.0, 3.0]


def test_real_mode_runs_caver(tmp_path: Path, monkeypatch) -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    from tools import caver

    caver_script = tmp_path / "caver.sh"
    caver_script.write_text(
        textwrap.dedent(
            """\
#!/usr/bin/env python3
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("-p", required=True)
parser.add_argument("-o", required=True)
args = parser.parse_args()

out_dir = Path(args.o)
out_dir.mkdir(parents=True, exist_ok=True)
csv_path = out_dir / "tunnels.csv"
csv_path.write_text(
    "tunnel_id,length,bottleneck_radius,throughput,curvature,lining_residues\\n"
    "1,18.5,1.1,0.7,0.35,A:6;A:10;A:14\\n",
    encoding="utf-8",
)
"""
        ),
        encoding="utf-8",
    )
    caver_script.chmod(0o755)
    _prepend_path(tmp_path, monkeypatch)

    pdb_path = tmp_path / "variant.pdb"
    pdb_path.write_text("ATOM", encoding="utf-8")
    output_path = tmp_path / "outputs" / "tunnels.json"

    caver.run(
        inputs=[pdb_path],
        outputs={"tunnels": output_path},
        params={},
        workdir=tmp_path,
        mode="real",
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["tunnels"][0]["tunnel_id"] == "tunnel-1"
    assert data["tunnels"][0]["bottleneck_radius"] == 1.1


def test_real_mode_runs_vina(tmp_path: Path, monkeypatch) -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    from tools import vina

    vina_script = tmp_path / "vina"
    vina_script.write_text(
        textwrap.dedent(
            """\
#!/usr/bin/env python3
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--receptor", required=True)
parser.add_argument("--ligand", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--log", required=True)
args = parser.parse_args()

out_path = Path(args.out)
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text("POSE1", encoding="utf-8")
pose2 = out_path.parent / "vina_pose_2.pdbqt"
pose2.write_text("POSE2", encoding="utf-8")

log_path = Path(args.log)
log_path.write_text(
    "-----+------------+----------+----------\\n"
    "   1     -7.5      0.0      0.0\\n"
    "   2     -6.1      0.0      0.0\\n",
    encoding="utf-8",
)
"""
        ),
        encoding="utf-8",
    )
    vina_script.chmod(0o755)
    _prepend_path(tmp_path, monkeypatch)

    pdb_path = tmp_path / "variant.pdb"
    pdb_path.write_text("ATOM", encoding="utf-8")
    output_path = tmp_path / "outputs" / "docking.json"

    vina.run(
        inputs=[pdb_path],
        outputs={"docking": output_path},
        params={},
        workdir=tmp_path,
        mode="real",
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["method"] == "vina"
    assert data["best_affinity"] == -7.5
    assert data["poses"][1]["rank"] == 2


def test_real_mode_runs_diffdock(tmp_path: Path, monkeypatch) -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.append(str(scripts_dir))
    from tools import diffdock

    diffdock_script = tmp_path / "diffdock"
    diffdock_script.write_text(
        textwrap.dedent(
            """\
#!/usr/bin/env python3
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--protein", required=True)
parser.add_argument("--ligand", required=True)
parser.add_argument("--out_dir", required=True)
args = parser.parse_args()

out_dir = Path(args.out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
csv_path = out_dir / "ranking.csv"
csv_path.write_text(
    "rank,score,path\\n"
    "1,0.62,poses/diffdock_pose_1.sdf\\n"
    "2,0.55,poses/diffdock_pose_2.sdf\\n",
    encoding="utf-8",
)
"""
        ),
        encoding="utf-8",
    )
    diffdock_script.chmod(0o755)
    _prepend_path(tmp_path, monkeypatch)

    pdb_path = tmp_path / "variant.pdb"
    pdb_path.write_text("ATOM", encoding="utf-8")
    output_path = tmp_path / "outputs" / "docking.json"

    diffdock.run(
        inputs=[pdb_path],
        outputs={"docking": output_path},
        params={},
        workdir=tmp_path,
        mode="real",
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["method"] == "diffdock"
    assert data["top_confidence"] == 0.62
    assert data["poses"][0]["path"] == "poses/diffdock_pose_1.sdf"
