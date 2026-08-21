"""Implementation-free HTTP client and contract guard for public @2."""

from .v2 import ClientHttpRequest
from .v2 import ClientHttpResponse
from .v2 import ClientHttpTransportPort
from .v2 import OpenZymeClientContractError
from .v2 import OpenZymeV2Client
from .v2 import VerifiedServerContract
from .v2 import parse_file_workspace_public_v2

COMPONENT_ID = "openzyme.client"
COMPONENT_KIND = "client"
MIGRATION_STATE = "target_implemented_not_cutover"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "ClientHttpRequest",
    "ClientHttpResponse",
    "ClientHttpTransportPort",
    "MIGRATION_STATE",
    "OpenZymeClientContractError",
    "OpenZymeV2Client",
    "VerifiedServerContract",
    "parse_file_workspace_public_v2",
]
