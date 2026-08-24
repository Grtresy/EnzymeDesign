"""HTTP admission for the durable Standard runtime-drain command."""

from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import IdGeneratorPort
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_host_api import HostV2CommandError
from openzyme_host_api import HostV2MutationInvocation
from openzyme_kernel.runtime_command_application import RuntimeCommandAdmissionCommand
from openzyme_kernel.runtime_command_application import (
    RuntimeCommandKernelApplicationService,
)

from .coordination_routes import build_standard_command_context


@dataclass(slots=True)
class StandardBoundedRuntimeDrainApplication:
    """Admit one bounded durable command without executing an Agent turn."""

    commands: RuntimeCommandKernelApplicationService
    ids: IdGeneratorPort

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        payload = dict(invocation.payload)
        max_signals = _positive(payload.pop("max_signals", None), "max_signals")
        max_steps = _positive(
            payload.pop("max_steps_per_agent", None),
            "max_steps_per_agent",
        )
        auto_enqueue = payload.pop("auto_enqueue_ready_tasks", False)
        if (
            payload
            or max_signals > 64
            or max_steps > 128
            or not isinstance(auto_enqueue, bool)
            or auto_enqueue
        ):
            raise _drain_error(
                "runtime_drain_payload_invalid",
                "Runtime drain payload exceeds its closed bounds or requests "
                "unsupported automatic task enqueue",
                status_code=422,
            )
        return self.commands.admit(
            RuntimeCommandAdmissionCommand(
                context=build_standard_command_context(invocation, ids=self.ids),
                max_signals=max_signals,
                max_steps_per_agent=max_steps,
                auto_enqueue_ready_tasks=auto_enqueue,
            )
        )


def _positive(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _drain_error(
            "runtime_drain_payload_invalid",
            f"{field_name} must be a positive integer",
            status_code=422,
        )
    return value


def _drain_error(
    code: str,
    message: str,
    *,
    status_code: int = 409,
) -> HostV2CommandError:
    return HostV2CommandError(
        code,
        message,
        status_code=status_code,
        mutation_applied=False,
        effect_certainty="no_effect",
    )


__all__ = ["StandardBoundedRuntimeDrainApplication"]
