from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
import json
from typing import Any
from typing import Protocol

from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureRecoverability
from openzyme_domain import RetryEligibility

from .failure_observations import record_failure_observation
from .public_diagnostics import sanitize_public_diagnostic_payload
from .public_diagnostics import sanitize_public_diagnostic_text
from .public_diagnostics import safe_public_machine_identifier


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    task_id: str | None = None
    lane_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    tool_name: str
    ok: bool
    content: str
    task_id: str | None = None
    lane_id: str | None = None
    status: str | None = None
    summary: str | None = None
    error_code: str | None = None
    hint: str | None = None
    details: dict[str, Any] | None = None
    failure_observation: dict[str, Any] | None = None
    terminal_action: str | None = None
    terminates_turn: bool = False

    def envelope(self) -> dict[str, Any]:
        details = dict(self.details or {})
        envelope: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status or ("ok" if self.ok else "failed"),
            "summary": self.summary or self.content,
            "error_code": self.error_code,
            "hint": self.hint,
            "details": details,
            "failure_observation": self.failure_observation,
            "content": self.content,
            "terminal_action": self.terminal_action,
            "terminates_turn": self.terminates_turn,
        }
        try:
            envelope["payload"] = json.loads(self.content)
        except (TypeError, json.JSONDecodeError):
            pass
        return envelope

    def to_tool_message_content(self) -> str:
        return json.dumps(self.envelope(), sort_keys=True)


ToolHandler = Callable[[Any, ToolInvocation], ToolResult | str]


def sanitize_tool_result_diagnostics(result: ToolResult) -> ToolResult:
    safe_status = safe_public_machine_identifier(
        result.status,
        fallback="ok" if result.ok else "failed",
    )
    safe_error_code = safe_public_machine_identifier(
        result.error_code,
        fallback=None if result.ok else "tool_error",
    )
    safe_terminal_action = safe_public_machine_identifier(
        result.terminal_action,
        fallback=None,
    )
    if result.ok:
        return replace(
            result,
            status=safe_status,
            error_code=safe_error_code,
            terminal_action=safe_terminal_action,
        )
    try:
        parsed_content = json.loads(result.content)
    except (TypeError, json.JSONDecodeError):
        public_content = sanitize_public_diagnostic_text(result.content)
    else:
        if isinstance(parsed_content, (dict, list)):
            public_content = json.dumps(
                sanitize_public_diagnostic_payload(parsed_content),
                sort_keys=True,
            )
        else:
            public_content = sanitize_public_diagnostic_text(result.content)
    safe_details = sanitize_public_diagnostic_payload(result.details or {})
    safe_failure = sanitize_public_diagnostic_payload(result.failure_observation or {})
    return replace(
        result,
        status=safe_status,
        content=public_content,
        summary=None
        if result.summary is None
        else sanitize_public_diagnostic_text(result.summary),
        hint=None
        if result.hint is None
        else sanitize_public_diagnostic_text(result.hint),
        details=dict(safe_details) if isinstance(safe_details, dict) else {},
        failure_observation=(
            dict(safe_failure) if isinstance(safe_failure, dict) else None
        )
        if result.failure_observation is not None
        else None,
        error_code=safe_error_code,
        terminal_action=safe_terminal_action,
    )


class ToolSideEffect(StrEnum):
    READ = "read"
    WRITE = "write"
    APPROVAL = "approval"
    EXTERNAL = "external"


@dataclass(frozen=True, slots=True)
class ToolGovernance:
    role_scope: tuple[str, ...] = ()
    supports_parallel: bool = False
    side_effect: ToolSideEffect = ToolSideEffect.WRITE
    approval_required: bool = False
    result_budget_policy: str = "default"

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "role_scope": list(self.role_scope),
            "supports_parallel": self.supports_parallel,
            "side_effect": self.side_effect.value,
            "approval_required": self.approval_required,
            "result_budget_policy": self.result_budget_policy,
        }


@dataclass(frozen=True, slots=True)
class ToolValidationError:
    status: str
    message: str
    error_code: str | None = None
    hint: str | None = None
    details: dict[str, Any] | None = None

    def to_tool_result(self, invocation: ToolInvocation) -> ToolResult:
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            content=self.message,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status=self.status,
            summary=self.message,
            error_code=self.error_code or self.status,
            hint=self.hint,
            details=self.details,
        )


def _missing_required_value(arguments: dict[str, Any], field_name: str) -> bool:
    return field_name not in arguments or arguments[field_name] in (None, "")


def _task_delegate_missing_required_message(
    field_name: str, input_schema: dict[str, Any]
) -> str | None:
    if field_name == "task_id":
        return (
            "Cannot delegate a task without task_id. "
            "Create or select a task first, then delegate it."
        )
    if field_name == "agent_role":
        properties = input_schema.get("properties") or {}
        field_schema = properties.get("agent_role") or {}
        enum_values = (
            field_schema.get("enum") if isinstance(field_schema, dict) else None
        )
        suffix = (
            f" Choose one of: {', '.join(str(value) for value in enum_values)}."
            if enum_values
            else ""
        )
        return f"Cannot delegate a task without agent_role.{suffix}"
    return None


def validate_arguments_against_schema(
    *,
    tool_name: str,
    input_schema: dict[str, Any],
    arguments: dict[str, Any],
) -> ToolValidationError | None:
    required = tuple(input_schema.get("required") or ())
    missing = [
        field_name
        for field_name in required
        if _missing_required_value(arguments, str(field_name))
    ]
    if missing:
        if tool_name == "task.delegate" and len(missing) == 1:
            message = _task_delegate_missing_required_message(
                str(missing[0]), input_schema
            )
            if message is not None:
                return ToolValidationError(
                    status="invalid_tool_arguments",
                    message=message,
                    error_code="invalid_tool_arguments",
                    hint="Fix the task.delegate arguments before retrying.",
                    details={"missing": [str(value) for value in missing]},
                )
        return ToolValidationError(
            status="invalid_tool_arguments",
            message=(
                f"Cannot call {tool_name}; missing required fields: "
                f"{', '.join(str(value) for value in missing)}."
            ),
            error_code="invalid_tool_arguments",
            hint="Provide all required tool arguments before retrying.",
            details={"missing": [str(value) for value in missing]},
        )
    properties = input_schema.get("properties") or {}
    for field_name, field_schema in properties.items():
        if field_name not in arguments or not isinstance(field_schema, dict):
            continue
        enum_values = field_schema.get("enum")
        if enum_values is not None and arguments[field_name] not in enum_values:
            return ToolValidationError(
                status="invalid_tool_arguments",
                message=(
                    f"Cannot call {tool_name}; invalid {field_name}: "
                    f"{arguments[field_name]!r}. Choose one of: "
                    f"{', '.join(str(value) for value in enum_values)}."
                ),
                error_code="invalid_tool_arguments",
                hint="Choose a valid enum value from the current tool schema.",
                details={
                    "field": str(field_name),
                    "value": arguments[field_name],
                    "allowed": list(enum_values),
                },
            )
    return None


@dataclass(frozen=True, slots=True)
class AgentStepContext:
    step_id: str
    session_id: str
    agent_id: str
    actor_kind: str
    role: str
    call_index: int
    task_id: str | None = None
    lane_id: str | None = None
    correlation_id: str | None = None
    signal_id: str | None = None
    wakeup_reason: str | None = None
    restore_context_digest: str | None = None
    tool_catalog_digest: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "actor_kind": self.actor_kind,
            "role": self.role,
            "call_index": self.call_index,
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "correlation_id": self.correlation_id,
            "signal_id": self.signal_id,
            "wakeup_reason": self.wakeup_reason,
            "restore_context_digest": self.restore_context_digest,
            "tool_catalog_digest": self.tool_catalog_digest,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ToolSpec:
    tool_name: str
    description: str
    input_schema: dict[str, Any]

    def to_openai_tool(self) -> dict[str, Any]:
        # Compatibility helper only. Runtime provider requests should use
        # ProviderToolAdapter so canonical names and provider-safe names stay
        # separated.
        return {
            "type": "function",
            "function": {
                "name": self.tool_name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolRuntime(Protocol):
    tool_name: str

    def spec(self, step_context: AgentStepContext) -> ToolSpec: ...

    def is_visible(self, step_context: AgentStepContext) -> bool: ...

    def governance(self, step_context: AgentStepContext) -> ToolGovernance: ...

    def validate(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolValidationError | None: ...

    def dispatch(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        runtime_context: Any,
    ) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class LegacyFunctionToolRuntime:
    tool_name: str
    handler: ToolHandler
    tool_spec: ToolSpec

    def spec(self, step_context: AgentStepContext) -> ToolSpec:
        del step_context
        return self.tool_spec

    def is_visible(self, step_context: AgentStepContext) -> bool:
        del step_context
        return True

    def governance(self, step_context: AgentStepContext) -> ToolGovernance:
        del step_context
        return ToolGovernance(
            role_scope=(),
            supports_parallel=False,
            side_effect=ToolSideEffect.WRITE,
            approval_required=False,
            result_budget_policy="default",
        )

    def validate(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolValidationError | None:
        del step_context
        return validate_arguments_against_schema(
            tool_name=invocation.tool_name,
            input_schema=self.tool_spec.input_schema,
            arguments=invocation.arguments,
        )

    def dispatch(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        runtime_context: Any,
    ) -> ToolResult:
        del step_context
        try:
            result = self.handler(runtime_context, invocation)
        except (KeyError, TypeError, ValueError) as exc:
            public_error = sanitize_public_diagnostic_text(str(exc)).strip()
            message = (
                f"Tool {invocation.tool_name} failed: "
                f"{public_error or exc.__class__.__name__}"
            )
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=message,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                status="invalid_tool_arguments",
                summary=message,
                error_code="invalid_tool_arguments",
                hint="Fix the tool arguments or referenced task/lane/session state before retrying.",
                details={"exception_type": exc.__class__.__name__},
            )
        if isinstance(result, ToolResult):
            return sanitize_tool_result_diagnostics(result)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=result,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="ok",
            summary=result,
        )


_REMOVED_WORKSPACE_TOOL_PREFIXES = (
    "arti" + "fact.",
    "arti" + "facts.",
    "scientific." + "arti" + "fact.",
    "sandbox." + "file.",
    "hpc.stage_" + "arti" + "fact",
    "hpc.fetch_" + "outputs",
)


def _is_removed_workspace_tool(tool_name: str) -> bool:
    return tool_name.startswith(_REMOVED_WORKSPACE_TOOL_PREFIXES)


@dataclass(slots=True)
class ToolRouter:
    runtimes: dict[str, ToolRuntime]
    dispatch_context: Any

    def registered_tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.runtimes))

    def model_visible_specs(
        self, step_context: AgentStepContext
    ) -> tuple[ToolSpec, ...]:
        return tuple(
            runtime.spec(step_context)
            for runtime in self.runtimes.values()
            if self.is_visible(step_context, runtime)
        )

    def governance(
        self, step_context: AgentStepContext, tool_name: str
    ) -> ToolGovernance | None:
        runtime = self.runtimes.get(tool_name)
        if runtime is None:
            return None
        return runtime.governance(step_context)

    def is_visible(self, step_context: AgentStepContext, runtime: ToolRuntime) -> bool:
        if not runtime.is_visible(step_context):
            return False
        governance = runtime.governance(step_context)
        if not governance.role_scope:
            return True
        return (
            step_context.role in governance.role_scope
            or step_context.actor_kind in governance.role_scope
            or step_context.agent_id in governance.role_scope
        )

    def validate(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolValidationError | None:
        runtime = self.runtimes.get(invocation.tool_name)
        if runtime is None:
            if _is_removed_workspace_tool(invocation.tool_name):
                return ToolValidationError(
                    status="removed_tool_current_contract",
                    message=(
                        f"tool {invocation.tool_name!r} was removed from file_workspace_public@1"
                    ),
                    error_code="removed_tool_current_contract",
                    hint=(
                        "Use the native workspace and an explicitly exposed revision, publication, or external-job operation; no replacement action was inferred."
                    ),
                    details={
                        "tool_name": invocation.tool_name,
                        "contract_id": "file_workspace_public@1",
                        "retryable": False,
                        "replacement_inferred": False,
                    },
                )
            return ToolValidationError(
                status="unknown_tool",
                message=f"unknown tool: {invocation.tool_name}",
                error_code="unknown_tool",
                hint="Use one of the tools exposed in the current V3 tool catalog.",
                details={"tool_name": invocation.tool_name},
            )
        if not self.is_visible(step_context, runtime):
            visible_names = sorted(
                name
                for name, candidate in self.runtimes.items()
                if self.is_visible(step_context, candidate)
            )
            return ToolValidationError(
                status="tool_not_visible",
                message=(
                    f"Tool {invocation.tool_name!r} is registered but is not "
                    "visible in the current agent step."
                ),
                error_code="tool_not_visible",
                hint="Use one of the tools exposed in the current V3 tool catalog.",
                details={
                    "tool_name": invocation.tool_name,
                    "visible_tools": visible_names,
                },
            )
        return runtime.validate(step_context, invocation)

    def dispatch(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolResult:
        runtime = self.runtimes.get(invocation.tool_name)
        if runtime is None:
            removed = _is_removed_workspace_tool(invocation.tool_name)
            return self._attach_failure_observation(
                step_context,
                invocation,
                ToolResult(
                    call_id=invocation.call_id,
                    tool_name=invocation.tool_name,
                    ok=False,
                    content=(
                        f"tool removed by file_workspace_public@1: {invocation.tool_name}"
                        if removed
                        else f"unknown tool: {invocation.tool_name}"
                    ),
                    task_id=invocation.task_id,
                    lane_id=invocation.lane_id,
                    status=(
                        "removed_tool_current_contract" if removed else "unknown_tool"
                    ),
                    summary=(
                        f"Tool {invocation.tool_name!r} was removed from the current contract."
                        if removed
                        else f"Tool {invocation.tool_name!r} is not registered."
                    ),
                    error_code=(
                        "removed_tool_current_contract" if removed else "unknown_tool"
                    ),
                    hint=(
                        "Use the native workspace and an explicitly exposed control-plane operation; no replacement action was inferred."
                        if removed
                        else "Use one of the tools exposed in the current V3 tool catalog."
                    ),
                    details=(
                        {
                            "contract_id": "file_workspace_public@1",
                            "retryable": False,
                            "replacement_inferred": False,
                        }
                        if removed
                        else None
                    ),
                ),
                governance=ToolGovernance(side_effect=ToolSideEffect.READ),
            )
        validation_error = self.validate(step_context, invocation)
        if validation_error is not None:
            return self._attach_failure_observation(
                step_context,
                invocation,
                sanitize_tool_result_diagnostics(
                    validation_error.to_tool_result(invocation)
                ),
                governance=(
                    runtime.governance(step_context)
                    if runtime is not None
                    else ToolGovernance(side_effect=ToolSideEffect.READ)
                ),
            )
        governance = runtime.governance(step_context)
        if governance.side_effect is not ToolSideEffect.READ:
            repositories = getattr(self.dispatch_context, "repositories", None)
            assert_fence = getattr(repositories, "assert_runtime_write_fence", None)
            if callable(assert_fence):
                try:
                    assert_fence(session_id=step_context.session_id)
                except RuntimeError as exc:
                    message = (
                        "Tool execution rejected because the session runtime lease "
                        "is no longer active."
                    )
                    result = ToolResult(
                        call_id=invocation.call_id,
                        tool_name=invocation.tool_name,
                        ok=False,
                        content=message,
                        task_id=invocation.task_id,
                        lane_id=invocation.lane_id,
                        status="runtime_fencing_rejected",
                        summary=message,
                        error_code="runtime_fencing_rejected",
                        hint="Allow the active runtime owner to resume this work.",
                        details={"reason": sanitize_public_diagnostic_text(str(exc))},
                    )
                    self._attach_failure_observation(
                        step_context,
                        invocation,
                        result,
                        governance=governance,
                        private_diagnostic=exc,
                    )
                    raise
        try:
            mutation_scope_factory = getattr(
                self.dispatch_context,
                "tool_mutation_writer_scope",
                None,
            )
            mutation_scope = (
                mutation_scope_factory(
                    tool_name=invocation.tool_name,
                    call_id=invocation.call_id,
                )
                if governance.side_effect is not ToolSideEffect.READ
                and callable(mutation_scope_factory)
                else nullcontext(None)
            )
            with mutation_scope:
                result = sanitize_tool_result_diagnostics(
                    runtime.dispatch(
                        step_context,
                        invocation,
                        self.dispatch_context,
                    )
                )
            if result.ok:
                return result
            return self._attach_failure_observation(
                step_context,
                invocation,
                result,
                governance=governance,
            )
        except Exception as exc:
            if self._is_boundary_fatal_exception(exc, governance=governance):
                self._record_exception_observation(
                    step_context,
                    invocation,
                    governance=governance,
                    exc=exc,
                    boundary_fatal=True,
                )
                raise
            if governance.side_effect is ToolSideEffect.READ:
                return self._ordinary_exception_result(
                    step_context,
                    invocation,
                    governance=governance,
                    exc=exc,
                )
            repositories = getattr(self.dispatch_context, "repositories", None)
            assert_fence = getattr(repositories, "assert_runtime_write_fence", None)
            if callable(assert_fence):
                try:
                    assert_fence(session_id=step_context.session_id)
                except RuntimeError:
                    self._record_exception_observation(
                        step_context,
                        invocation,
                        governance=governance,
                        exc=exc,
                        boundary_fatal=True,
                        error_code="runtime_fencing_rejected",
                    )
                    raise
            return self._ordinary_exception_result(
                step_context,
                invocation,
                governance=governance,
                exc=exc,
            )

    @staticmethod
    def _is_boundary_fatal_exception(
        exc: Exception,
        *,
        governance: ToolGovernance,
    ) -> bool:
        if governance.side_effect is ToolSideEffect.APPROVAL or (
            governance.side_effect is ToolSideEffect.EXTERNAL
            and governance.approval_required
        ):
            return True
        error_code = str(getattr(exc, "error_code", "")).casefold()
        class_name = exc.__class__.__name__.casefold()
        return (
            "fenc" in error_code
            or "authority" in error_code
            or "integrity" in error_code
            or "fencing" in class_name
            or class_name.endswith("authorityerror")
            or class_name.endswith("integrityerror")
        )

    def _ordinary_exception_result(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        *,
        governance: ToolGovernance,
        exc: Exception,
    ) -> ToolResult:
        observation = self._record_exception_observation(
            step_context,
            invocation,
            governance=governance,
            exc=exc,
            boundary_fatal=False,
        )
        message = (
            f"Tool {invocation.tool_name} failed with a recoverable runtime error. "
            f"Inspect failure {observation.failure_id}, then repair, choose another "
            "strategy, request help, or explicitly block the task."
        )
        return sanitize_tool_result_diagnostics(
            ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=message,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                status="tool_runtime_error",
                summary=message,
                error_code="tool_runtime_error",
                hint=(
                    "Do not repeat blindly. Use the structured facts and retry "
                    "eligibility to choose the next action."
                ),
                details={
                    "exception_type": exc.__class__.__name__,
                    "side_effect": governance.side_effect.value,
                },
                failure_observation=observation.to_dict(),
            )
        )

    def _record_exception_observation(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        *,
        governance: ToolGovernance,
        exc: Exception,
        boundary_fatal: bool,
        error_code: str | None = None,
    ):
        is_external = (
            governance.side_effect is ToolSideEffect.EXTERNAL
            and governance.approval_required
        )
        resolved_error_code = (
            error_code
            or safe_public_machine_identifier(
                getattr(exc, "error_code", None),
                fallback=(
                    "external_effect_outcome_unknown"
                    if is_external
                    else "tool_runtime_error"
                ),
            )
            or "tool_runtime_error"
        )
        repositories = getattr(self.dispatch_context, "repositories", None)
        return record_failure_observation(
            repositories,
            session_id=step_context.session_id,
            task_id=invocation.task_id or step_context.task_id,
            lane_id=invocation.lane_id or step_context.lane_id,
            agent_id=step_context.agent_id,
            source_kind="tool_invocation",
            source_ref=invocation.call_id,
            source_version=step_context.step_id,
            phase="dispatch",
            failure_class=(
                FailureClass.CONTROLLED_EFFECT
                if is_external
                else (
                    FailureClass.PROVIDER
                    if governance.side_effect is ToolSideEffect.EXTERNAL
                    else FailureClass.TOOL
                )
            ),
            recoverability=(
                FailureRecoverability.RECONCILIATION_REQUIRED
                if is_external
                else (
                    FailureRecoverability.RUNTIME_RETRY
                    if boundary_fatal
                    else FailureRecoverability.AGENT_CAN_REPLAN
                )
            ),
            effect_certainty=(
                ExternalEffectCertainty.DISPATCH_IN_DOUBT
                if is_external
                else ExternalEffectCertainty.TERMINAL_KNOWN
            ),
            retry_eligibility=(
                RetryEligibility.RECONCILE_REQUIRED
                if is_external
                else RetryEligibility.TERMINAL
            ),
            actor_kind=FailureActorKind.HARNESS,
            error_code=resolved_error_code,
            safe_summary=(
                "External tool dispatch failed with an outcome that requires "
                "reconciliation."
                if is_external
                else "Tool execution failed at a known local boundary."
            ),
            safe_hint=(
                "Reconcile the exact external operation before retrying or "
                "creating replacement work."
                if is_external
                else "Inspect the failure facts before choosing repair, replan, or refusal."
            ),
            facts={
                "tool_name": invocation.tool_name,
                "side_effect": governance.side_effect.value,
                "boundary_fatal": boundary_fatal,
                "exception_type": exc.__class__.__name__,
                "public_error": sanitize_public_diagnostic_text(str(exc)),
            },
            private_diagnostic={
                "exception_type": exc.__class__.__name__,
                "message": str(exc),
            },
        )

    def _attach_failure_observation(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        result: ToolResult,
        *,
        governance: ToolGovernance,
        private_diagnostic: object | None = None,
    ) -> ToolResult:
        if result.ok or result.failure_observation is not None:
            return sanitize_tool_result_diagnostics(result)
        error_code = result.error_code or result.status or "tool_error"
        details = dict(result.details or {})
        validation = (
            error_code
            in {
                "invalid_tool_arguments",
                "unknown_tool",
                "tool_not_visible",
            }
            or details.get("precondition_rejected") is True
        )
        try:
            effect_certainty = ExternalEffectCertainty(
                str(details.get("effect_certainty"))
            )
        except ValueError:
            effect_certainty = (
                ExternalEffectCertainty.NO_EFFECT
                if validation
                else ExternalEffectCertainty.TERMINAL_KNOWN
            )
        try:
            retry_eligibility = RetryEligibility(str(details.get("retry_eligibility")))
        except ValueError:
            retry_eligibility = (
                RetryEligibility.SAME_PHASE_SAFE
                if validation
                else RetryEligibility.TERMINAL
            )
        try:
            recoverability = FailureRecoverability(str(details.get("recoverability")))
        except ValueError:
            recoverability = (
                FailureRecoverability.RECONCILIATION_REQUIRED
                if effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else (
                    FailureRecoverability.AGENT_CAN_RETRY
                    if validation
                    else FailureRecoverability.AGENT_CAN_REPLAN
                )
            )
        observation = record_failure_observation(
            getattr(self.dispatch_context, "repositories", None),
            session_id=step_context.session_id,
            task_id=invocation.task_id or step_context.task_id,
            lane_id=invocation.lane_id or step_context.lane_id,
            agent_id=step_context.agent_id,
            source_kind="tool_invocation",
            source_ref=invocation.call_id,
            source_version=step_context.step_id,
            phase="validation" if validation else "dispatch",
            failure_class=FailureClass.VALIDATION if validation else FailureClass.TOOL,
            recoverability=recoverability,
            effect_certainty=effect_certainty,
            retry_eligibility=retry_eligibility,
            actor_kind=FailureActorKind.HARNESS,
            error_code=error_code,
            safe_summary=result.summary or result.content,
            safe_hint=result.hint,
            facts={
                **details,
                "tool_name": invocation.tool_name,
                "side_effect": governance.side_effect.value,
            },
            private_diagnostic=private_diagnostic,
        )
        return sanitize_tool_result_diagnostics(
            replace(result, failure_observation=observation.to_dict())
        )


class ToolRegistryProtocol:
    def register(self, tool_name: str, handler: ToolHandler) -> None: ...

    def register_runtime(self, runtime: ToolRuntime) -> None: ...


__all__ = [
    "AgentStepContext",
    "LegacyFunctionToolRuntime",
    "ToolHandler",
    "ToolGovernance",
    "ToolInvocation",
    "ToolRegistryProtocol",
    "ToolRouter",
    "ToolRuntime",
    "ToolSideEffect",
    "ToolSpec",
    "ToolResult",
    "ToolValidationError",
    "sanitize_tool_result_diagnostics",
    "validate_arguments_against_schema",
]
