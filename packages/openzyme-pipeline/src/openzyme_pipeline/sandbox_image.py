from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


DEFAULT_IMAGE = "localhost/openzyme-pipeline-sandbox:dev"


def build_image(*, image: str = DEFAULT_IMAGE) -> None:
    with tempfile.TemporaryDirectory(prefix="openzyme-pipeline-image-") as tmp:
        root = Path(tmp)
        (root / "Containerfile").write_text(
            "\n".join(
                (
                    "FROM python:3.12-slim",
                    "RUN useradd --create-home --uid 10001 pipeline",
                    "WORKDIR /openzyme/work",
                    "COPY openzyme_pipeline /tmp/openzyme_pipeline",
                    "RUN pip install --no-cache-dir /tmp/openzyme_pipeline",
                    "USER 10001:10001",
                    'ENV PYTHONUNBUFFERED=1 OPENZYME_CONTROL_SOCKET="/openzyme/control.sock"',
                    'CMD ["python", "/openzyme/work/pipeline.py"]',
                )
            ),
            encoding="utf-8",
        )
        package_root = Path(__file__).resolve().parents[2]
        subprocess.run(["cp", "-R", str(package_root), str(root / "openzyme_pipeline")], check=True)
        subprocess.run(["podman", "build", "-t", image, "-f", str(root / "Containerfile"), str(root)], check=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    build = subcommands.add_parser("build")
    build.add_argument("--image", default=DEFAULT_IMAGE)
    args = parser.parse_args(argv)
    if args.command == "build":
        build_image(image=args.image)


if __name__ == "__main__":
    main()
