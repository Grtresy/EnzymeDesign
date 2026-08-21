"""EnzymeDesign public product contracts and composition contributions."""

from .provider_contracts import BIO_PROVIDER_PORT_CONTRACT
from .provider_contracts import BIO_PROVIDER_PORT_CONTRACT_DIGEST
from .provider_contracts import BIO_PROVIDER_PORT_ID
from .provider_contracts import BioProviderPort
from .provider_contracts import DownloadedProviderAsset
from .provider_contracts import ProteinAnnotationRecord
from .provider_contracts import ProteinMetadataRecord
from .provider_contracts import SequenceProviderApplication
from .provider_contracts import StructureMetadataRecord

COMPONENT_ID = "enzymedesign.core"
COMPONENT_KIND = "product_contracts"
MIGRATION_STATE = "target_implemented_not_cutover"

__all__ = [
    "BIO_PROVIDER_PORT_CONTRACT",
    "BIO_PROVIDER_PORT_CONTRACT_DIGEST",
    "BIO_PROVIDER_PORT_ID",
    "BioProviderPort",
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "DownloadedProviderAsset",
    "MIGRATION_STATE",
    "ProteinAnnotationRecord",
    "ProteinMetadataRecord",
    "SequenceProviderApplication",
    "StructureMetadataRecord",
]
