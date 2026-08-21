#!/usr/bin/env python3
"""Generate the exact test resource manifest from a sealed pytest collection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.model import canonical_document_bytes  # noqa: E402
from scripts.test_gate.resource import build_resource_manifest  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPOSITORY_ROOT)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    repo_root = arguments.repo_root.resolve(strict=True)
    collection_path = arguments.collection.resolve(strict=True)
    document: Any = json.loads(collection_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(
        document.get("collection"), list
    ):
        raise SystemExit("collection must be a pytest observation document")
    manifest = build_resource_manifest(
        repo_root=repo_root,
        collection_records=document["collection"],
    )
    output = arguments.output.resolve()
    if output.parent != (repo_root / "scripts").resolve():
        raise SystemExit("output must be a direct child of the repository scripts/")
    output.write_bytes(canonical_document_bytes(manifest))
    print(manifest["self_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
