from __future__ import annotations

from pathlib import Path
import sys


# Keep shared helpers in this test directory importable without turning the
# monorepo's many ``tests`` directories into one conflicting top-level package.
TEST_ROOT = Path(__file__).resolve().parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))
