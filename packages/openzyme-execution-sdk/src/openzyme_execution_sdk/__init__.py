"""Domain-neutral SDK for controlled sandbox execution."""

from .client import CONTROL_SOCKET_FRAME_MAX_BYTES
from .client import CONTROL_SOCKET_IO_TIMEOUT_SECONDS
from .client import ControlClient
from .client import ExecutionSdkError
from .client import PipelineSdkError
from .client import call
from .client import canonical_digest
from .client import supervised_sandbox_mode
from .file_workspace_api import FILE_WORKSPACE_SDK_SCHEMA_ID
from .workspace_revision import WorkspaceRevisionJob
from .workspace_revision import submit
from .workload import ExecutionWorkloadInvocation
from .workload import submit_workload

COMPONENT_ID = "openzyme.execution.sdk"
COMPONENT_KIND = "sdk"
MIGRATION_STATE = "target_implemented_legacy_callers_pending"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    "CONTROL_SOCKET_FRAME_MAX_BYTES",
    "CONTROL_SOCKET_IO_TIMEOUT_SECONDS",
    "ControlClient",
    "ExecutionSdkError",
    "ExecutionWorkloadInvocation",
    "PipelineSdkError",
    "FILE_WORKSPACE_SDK_SCHEMA_ID",
    "WorkspaceRevisionJob",
    "call",
    "canonical_digest",
    "submit",
    "submit_workload",
    "supervised_sandbox_mode",
]
