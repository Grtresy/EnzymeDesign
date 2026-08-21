from openzyme_extension_spi import read_located_component_manifest

from openzyme_store_sqlite import SQLITE_STORE_ADAPTER_CONTRACT_DIGEST
from openzyme_store_sqlite import SQLITE_STORE_CONFIGURATION_SCHEMA_DIGEST
from openzyme_store_sqlite import SQLITE_STORE_PREFLIGHT_CONTRACT_DIGEST
from openzyme_store_sqlite.manifest_locator import locate_component_manifest


def test_sqlite_adapter_manifest_declares_control_store_port() -> None:
    manifest = read_located_component_manifest(locate_component_manifest())

    assert manifest.identity.component_id == "openzyme.store.sqlite"
    assert [item.contribution_id for item in manifest.port_contracts] == [
        "openzyme.control-store-port@1"
    ]
    assert manifest.identity.contract_digest == SQLITE_STORE_ADAPTER_CONTRACT_DIGEST
    assert manifest.port_contracts[0].contract_digest == (
        SQLITE_STORE_ADAPTER_CONTRACT_DIGEST
    )
    assert manifest.configuration_schema_digest == (
        SQLITE_STORE_CONFIGURATION_SCHEMA_DIGEST
    )
    assert manifest.preflight_contract_digest == (
        SQLITE_STORE_PREFLIGHT_CONTRACT_DIGEST
    )
