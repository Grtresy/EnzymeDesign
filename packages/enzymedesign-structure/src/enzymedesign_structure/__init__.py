"""EnzymeDesign structure analysis Product Plugin."""

from .contracts import *  # noqa: F403
from .contracts import __all__ as _contract_exports
from .drivers import *  # noqa: F403
from .drivers import __all__ as _driver_exports
from .manifest_locator import *  # noqa: F403
from .manifest_locator import __all__ as _locator_exports
from .runtime import *  # noqa: F403
from .runtime import __all__ as _runtime_exports

COMPONENT_ID = "enzymedesign.structure"
COMPONENT_KIND = "product_plugin"
MIGRATION_STATE = "target_implemented_not_cutover"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    *_contract_exports,
    *_driver_exports,
    *_locator_exports,
    *_runtime_exports,
]
