"""EnzymeDesign sequence and biological-resource Product Plugin."""

from .manifest_locator import SEQUENCE_COMPONENT_MANIFEST_DIGEST
from .manifest_locator import locate_component_manifest
from .runtime import *  # noqa: F403
from .runtime import __all__ as _runtime_exports
from .sequence import *  # noqa: F403
from .sequence import __all__ as _sequence_exports

COMPONENT_ID = "enzymedesign.sequence.toolpack"
COMPONENT_KIND = "product_plugin"
MIGRATION_STATE = "target_implemented_not_cutover"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    "SEQUENCE_COMPONENT_MANIFEST_DIGEST",
    "locate_component_manifest",
    *_runtime_exports,
    *_sequence_exports,
]
