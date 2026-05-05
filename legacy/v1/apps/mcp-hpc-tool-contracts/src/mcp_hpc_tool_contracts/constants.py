from __future__ import annotations

import os

ADAPTER_IDS: tuple[str, ...] = (
    "hhblits",
    "chai_fold",
    "alphafold3",
    "colabfold",
    "fpocket",
    "tunnels",
    "vina",
)

CANONICAL_WRAPPER_ENTRYPOINTS: dict[str, str] = {
    "alphafold3": "/opt/tools/alphafold3",
    "chai_fold": "/opt/tools/chai-lab",
    "colabfold": "/opt/tools/colabfold_batch",
}

CANONICAL_SIF_IMAGES: dict[str, str] = {
    "hhblits": "~/containers/hhsuite.sif",
    "fpocket": "~/containers/fpocket.sif",
    "tunnels": "~/containers/caverdock-1.2.sif",
    "vina": "~/containers/vina.sif",
}

HHBLITS_SPACK_FALLBACK = os.getenv("HHBLITS_SPACK_FALLBACK", "/opt/spack/bin/hhblits")

# Natural default invocation mode for each adapter when no cluster profile is set.
# Adapters that ship as SIF images default to "sif"; adapters that rely on
# host-installed wrappers (no SIF image available) default to "wrapper".
ADAPTER_DEFAULT_MODES: dict[str, str] = {
    "hhblits":    "sif",
    "chai_fold":  "wrapper",
    "alphafold3": "wrapper",
    "colabfold":  "wrapper",
    "fpocket":    "sif",
    "tunnels":    "sif",
    "vina":       "sif",
}
