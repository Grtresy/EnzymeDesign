"""Implementation-free runtime and process-isolation contracts."""

from .process import IsolatedProcessState
from .process import PROCESS_ISOLATION_RECEIPT_SCHEMA_VERSION
from .process import PROCESS_ISOLATION_REQUEST_SCHEMA_VERSION
from .process import PROCESS_ISOLATION_PORT_CONTRACT
from .process import PROCESS_ISOLATION_PORT_CONTRACT_DIGEST
from .process import ProcessIsolationPort
from .process import ProcessIsolationReceipt
from .process import ProcessIsolationRequest
from .runtime import AgentRuntimeAdapter
from .runtime import RUNTIME_MESSAGE_SCHEMA_VERSION
from .runtime import RUNTIME_TOOL_REQUEST_SCHEMA_VERSION
from .runtime import RUNTIME_TURN_COMMAND_SCHEMA_VERSION
from .runtime import RUNTIME_TURN_OUTCOME_SCHEMA_VERSION
from .runtime import RUNTIME_USAGE_SCHEMA_VERSION
from .runtime import RuntimeCapabilityGateway
from .runtime import RuntimeMessage
from .runtime import RuntimeMessageRole
from .runtime import RuntimeToolRequest
from .runtime import RuntimeToolInvocationError
from .runtime import RuntimeTurnCommand
from .runtime import RuntimeTurnDisposition
from .runtime import RuntimeTurnOutcome
from .runtime import RuntimeUsage

COMPONENT_ID = "openzyme.runtime.spi"
COMPONENT_KIND = "adapter_spi"
MIGRATION_STATE = "scaffold_not_activatable"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    "AgentRuntimeAdapter",
    "IsolatedProcessState",
    "PROCESS_ISOLATION_RECEIPT_SCHEMA_VERSION",
    "PROCESS_ISOLATION_REQUEST_SCHEMA_VERSION",
    "PROCESS_ISOLATION_PORT_CONTRACT",
    "PROCESS_ISOLATION_PORT_CONTRACT_DIGEST",
    "ProcessIsolationPort",
    "ProcessIsolationReceipt",
    "ProcessIsolationRequest",
    "RUNTIME_MESSAGE_SCHEMA_VERSION",
    "RUNTIME_TOOL_REQUEST_SCHEMA_VERSION",
    "RUNTIME_TURN_COMMAND_SCHEMA_VERSION",
    "RUNTIME_TURN_OUTCOME_SCHEMA_VERSION",
    "RUNTIME_USAGE_SCHEMA_VERSION",
    "RuntimeCapabilityGateway",
    "RuntimeMessage",
    "RuntimeMessageRole",
    "RuntimeToolRequest",
    "RuntimeToolInvocationError",
    "RuntimeTurnCommand",
    "RuntimeTurnDisposition",
    "RuntimeTurnOutcome",
    "RuntimeUsage",
]
