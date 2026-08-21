from __future__ import annotations

from pathlib import Path
import sys


# The monorepo has another package-local ``tests`` package.  Keep this helper
# import scoped to the kernel test directory instead of relying on the ambient
# top-level ``tests`` package selected by pytest's root collection.
TEST_ROOT = Path(__file__).resolve().parent
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))
