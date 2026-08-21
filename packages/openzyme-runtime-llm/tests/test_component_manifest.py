import json
import subprocess
import sys

from openzyme_extension_spi import read_located_component_manifest

from openzyme_runtime_llm import LLM_ADAPTER_CONFIGURATION_SCHEMA_DIGEST
from openzyme_runtime_llm import LLM_ADAPTER_PREFLIGHT_CONTRACT_DIGEST
from openzyme_runtime_llm import LLM_RUNTIME_ADAPTER_CONTRACT_DIGEST
from openzyme_runtime_llm.manifest_locator import locate_component_manifest


def test_llm_adapter_manifest_declares_agent_runtime_port() -> None:
    manifest = read_located_component_manifest(locate_component_manifest())

    assert manifest.identity.component_id == "openzyme.runtime.llm"
    assert [item.contribution_id for item in manifest.port_contracts] == [
        "openzyme.agent-runtime-adapter@1"
    ]
    assert manifest.port_contracts[0].contract_digest == (
        LLM_RUNTIME_ADAPTER_CONTRACT_DIGEST
    )
    assert manifest.configuration_schema_digest == (
        LLM_ADAPTER_CONFIGURATION_SCHEMA_DIGEST
    )
    assert manifest.preflight_contract_digest == (
        LLM_ADAPTER_PREFLIGHT_CONTRACT_DIGEST
    )


def test_locator_import_does_not_import_provider_or_read_environment() -> None:
    script = """
import json
import sys
from openzyme_runtime_llm.manifest_locator import locate_component_manifest
locator = locate_component_manifest()
runtime_modules = sorted(
    name for name in sys.modules
    if name in {
        'openzyme_runtime_llm.adapter',
        'openzyme_runtime_llm.configuration',
        'openzyme_runtime_llm.provider',
        'langchain',
        'langchain_openai',
    }
)
print(json.dumps({'component_id': locator.component_id, 'runtime_modules': runtime_modules}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert json.loads(completed.stdout) == {
        "component_id": "openzyme.runtime.llm",
        "runtime_modules": [],
    }
