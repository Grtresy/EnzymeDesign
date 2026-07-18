from __future__ import annotations

import json

import pytest

from openzyme_runtime import sanitize_public_diagnostic_payload
from openzyme_runtime import sanitize_public_diagnostic_text
from openzyme_runtime import AgentStepContext
from openzyme_runtime import LegacyFunctionToolRuntime
from openzyme_runtime import ToolInvocation
from openzyme_runtime import ToolResult
from openzyme_runtime import ToolSpec


@pytest.mark.parametrize(
    "private_value",
    (
        "/home/operator/private/config.toml",
        "/tmp/openzyme/run.sock",
        "/var/lib/openzyme/state",
        "/run/user/1000/podman.sock",
        r"C:\\Users\\operator\\secret.txt",
        r"\\server\\share\\private.txt",
        "file:///home/operator/private.txt",
        "~/private/config.toml",
        "/srv/openzyme/private/config.toml",
        "/etc/openzyme/private.conf",
        "/tmp",
        "/home",
        "D:/operator/private.txt",
        "/scratch/slurm/job-001/stderr",
        "/gpfs/project/private/input.fasta",
        "/lustre/work/private/result.csv",
        "/cluster/apps/private/tool",
        "/project/private/config.toml",
        "/private/var/run/private.sock",
        "/app/private/settings.json",
        "/code/private/module.py",
    ),
)
def test_public_diagnostic_text_redacts_embedded_private_locations(
    private_value: str,
) -> None:
    sanitized = sanitize_public_diagnostic_text(
        f"failed at {private_value} after validation"
    )

    assert private_value not in sanitized
    assert "[redacted-host-path]" in sanitized


def test_public_diagnostic_text_preserves_logical_workspace_and_maps_known_root() -> (
    None
):
    sanitized = sanitize_public_diagnostic_text(
        "statfs /tmp/attempt/sandboxes/sw_001/input; logical=/workspace/src/probe.py",
        path_replacements=(("/tmp/attempt/sandboxes/sw_001", "/workspace"),),
    )

    assert sanitized == "statfs /workspace/input; logical=/workspace/src/probe.py"


def test_public_diagnostic_text_redacts_credentials_and_is_idempotent() -> None:
    original = (
        "Bearer abc.def token=top-secret "
        "url=https://operator:password@example.test/path"
    )

    once = sanitize_public_diagnostic_text(original)
    twice = sanitize_public_diagnostic_text(once)

    assert once == twice
    assert "abc.def" not in once
    assert "top-secret" not in once
    assert "operator:password" not in once


@pytest.mark.parametrize(
    "private_value",
    (
        "client_secret=hunter2",
        "access_token=abc123",
        "refresh-token:abc123",
        "cookie=sessionid",
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "Set-Cookie: session=top-secret; Secure",
        "OPENAI_API_KEY=topsecret",
        "MICU_ACCESS_TOKEN=abc123",
        "DATABASE_PASSWORD=hunter2",
        "PROVIDER_CLIENT_SECRET=secret",
        "MICU_TOKEN=abc123",
        "PROVIDER_SECRET=abc123",
        "AUTHORIZATION_TOKEN=abc123",
        "provider_credential=raw-value",
        "private_key=raw-key",
        "PROVIDER_AUTHORIZATION=Basic dXNlcjpwYXNzd29yZA==",
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "AWS_SECRET_KEY=opaquevalue123",
        "GOOGLE_APPLICATION_CREDENTIALS=opaquecredential",
        "PRIVATE_KEY_DATA=opaquevalue",
        "PASSWORD_FILE=relative-secret-file",
        "AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountKey=opaquevalue",
        "MYSQL_PWD=opaquevalue",
        "REDISCLI_AUTH=opaquevalue",
        "clientSecret=opaquevalue",
        "accessToken=opaquevalue",
        "refreshToken=opaquevalue",
        "privateKey=opaquevalue",
        "storageUri=opaquevalue",
        "sourceUri=opaquevalue",
        "hostPath=opaquevalue",
        "remotePath=opaquevalue",
        "localPath=opaquevalue",
        "runnerConfig=opaquevalue",
        "connectionString=opaquevalue",
    ),
)
def test_public_diagnostic_text_redacts_embedded_credential_forms(
    private_value: str,
) -> None:
    sanitized = sanitize_public_diagnostic_text(f"provider rejected {private_value}")

    assert private_value not in sanitized
    assert "hunter2" not in sanitized
    assert "abc123" not in sanitized
    assert "sessionid" not in sanitized
    assert "dXNlcjpwYXNzd29yZA" not in sanitized


@pytest.mark.parametrize(
    "private_value",
    (
        "http://127.0.0.1:8080/debug?token=secret",
        "https://10.0.0.8/internal",
        "http://127.1/debug",
        "http://0x7f.0.0.1/private",
        "http://0x7f.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://[fe80::1]/private",
        "https://service.corp/status",
        "https://router.lan/status",
        "https://nas.home.arpa/status",
        "https://api.cluster/status",
        "https://service.namespace.svc/status",
        "https://vault.consul/status",
        "https://host.test/status",
        "https://host.invalid/status",
        "https://host.example/status",
        "sk-ant-abcdefghijklmnop",
        "ghp_abcdefghijklmnopqrstuvwxyz",
        "AKIAABCDEFGHIJKLMNOP",
        "eyJheader.payload.signature",
    ),
)
def test_public_diagnostic_text_redacts_private_urls_and_raw_secrets(
    private_value: str,
) -> None:
    sanitized = sanitize_public_diagnostic_text(f"provider failed: {private_value}")

    assert private_value not in sanitized
    assert "[redacted" in sanitized


def test_public_diagnostic_text_preserves_query_free_public_ipv4_url() -> None:
    original = "https://8.8.8.8/public"

    assert sanitize_public_diagnostic_text(original) == original


@pytest.mark.parametrize(
    "private_value",
    (
        "storage://tenant/private",
        "s3://private-bucket/object",
        "ssh://runner.internal/work",
        "postgresql://user:password@db.internal/openzyme",
        "redis://:hunter2@127.0.0.1/0",
        "mongodb://user:password@10.0.0.8/openzyme",
    ),
)
def test_public_diagnostic_text_redacts_private_locators(
    private_value: str,
) -> None:
    sanitized = sanitize_public_diagnostic_text(f"artifact={private_value}")

    assert private_value not in sanitized
    assert "[redacted-private-locator]" in sanitized


@pytest.mark.parametrize(
    "escaped_locator",
    (
        r"https:\/\/127.0.0.1:8080\/debug",
        r"postgresql:\/\/user:pass@db.internal\/openzyme",
    ),
)
def test_public_diagnostic_text_redacts_json_escaped_private_locator(
    escaped_locator: str,
) -> None:
    sanitized = sanitize_public_diagnostic_text(escaped_locator)

    assert "127.0.0.1" not in sanitized
    assert "user:pass" not in sanitized
    assert "[redacted" in sanitized


def test_public_diagnostic_text_does_not_map_workspace_prefix_siblings() -> None:
    sanitized = sanitize_public_diagnostic_text(
        "failed at /tmp/attempt/sw_001_evil/input",
        path_replacements=(("/tmp/attempt/sw_001", "/workspace"),),
    )

    assert "/workspace_evil" not in sanitized
    assert "[redacted-host-path]" in sanitized


@pytest.mark.parametrize(
    "query",
    (
        "query=AOX&size=25#results",
        "sv=2026-01-01&sig=deadbeef",
        "X-Amz-Signature=deadbeef",
        "X-Goog-Signature=deadbeef",
        "code=oauth-secret",
        "api%5Fkey=secret",
    ),
)
def test_public_diagnostic_text_strips_public_url_query_and_fragment(
    query: str,
) -> None:
    original = f"https://rest.uniprot.org/uniprotkb/search?{query}"

    assert (
        sanitize_public_diagnostic_text(original)
        == "https://rest.uniprot.org/uniprotkb/search"
    )


@pytest.mark.parametrize(
    "encoded_path",
    (
        r"{\"path\":\"\/home\/operator\/private.txt\"}",
        "%2Fhome%2Foperator%2Fprivate.txt",
    ),
)
def test_public_diagnostic_text_redacts_encoded_private_path(
    encoded_path: str,
) -> None:
    sanitized = sanitize_public_diagnostic_text(encoded_path)

    assert "operator" not in sanitized
    assert "[redacted-host-path]" in sanitized


@pytest.mark.parametrize(
    "private_identifier",
    (
        "sk-abcdefghijklmnop",
        "AKIAABCDEFGHIJKLMNOP",
    ),
)
def test_failed_tool_result_rejects_secret_shaped_machine_identifier(
    private_identifier: str,
) -> None:
    def error_handler(
        _context: object, invocation: ToolInvocation
    ) -> ToolResult:
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            content="provider failed",
            status=private_identifier,
            error_code=private_identifier,
        )

    runtime = LegacyFunctionToolRuntime(
        tool_name="example.tool",
        handler=error_handler,
        tool_spec=ToolSpec(
            tool_name="example.tool",
            description="test",
            input_schema={"type": "object", "properties": {}},
        ),
    )
    result = runtime.dispatch(
        AgentStepContext(
            step_id="step_1",
            session_id="sess_1",
            agent_id="agent:executor",
            actor_kind="agent",
            role="executor",
            call_index=0,
        ),
        ToolInvocation(
            call_id="call_1",
            tool_name="example.tool",
            arguments={},
        ),
        object(),
    )

    assert result.status == "failed"
    assert result.error_code == "tool_error"
    assert private_identifier not in result.to_tool_message_content()


def test_public_diagnostic_payload_recursively_redacts_strings() -> None:
    sanitized = sanitize_public_diagnostic_payload(
        {
            "message": "failed at /home/operator/private.txt",
            "nested": ["socket=/run/user/1000/private.sock", 7],
        }
    )

    assert sanitized == {
        "message": "failed at [redacted-host-path]",
        "nested": ["socket=[redacted-host-path]", 7],
    }


def test_public_diagnostic_payload_drops_sensitive_fields_without_hiding_usage() -> (
    None
):
    sanitized = sanitize_public_diagnostic_payload(
        {
            "access_token": "raw-access-token",
            "host_path": "/srv/private/location",
            "provider_credentials": {"user": "operator"},
            "secret": "raw-secret",
            "/home/operator/private-key": "value",
            "private_locator": "opaque-private-value",
            "local_path": "/custom/private/location",
            "set_cookie": "session=raw",
            "runner_config": {"endpoint": "private"},
            "provider_token": "raw-token",
            "session_cookie": "raw-cookie",
            "provider_authorization": "raw-authorization",
            "AWS_SECRET_ACCESS_KEY": "opaque",
            "MYSQL_PWD": "opaque",
            "REDISCLI_AUTH": "opaque",
            "AZURE_STORAGE_CONNECTION_STRING": "opaque",
            "clientSecret": "opaque",
            "accessToken": "opaque",
            "refreshToken": "opaque",
            "privateKey": "opaque",
            "storageUri": "opaque",
            "sourceUri": "opaque",
            "hostPath": "opaque",
            "remotePath": "opaque",
            "localPath": "opaque",
            "runnerConfig": "opaque",
            "connectionString": "opaque",
            "token_count": 42,
            "message": "safe",
        }
    )

    assert sanitized == {"token_count": 42, "message": "safe"}


def test_public_diagnostic_payload_preserves_already_redacted_compatible_field() -> (
    None
):
    sanitized = sanitize_public_diagnostic_payload(
        {
            "secret_token": "[redacted]",
            "provider_token": "raw-token",
            "access_token": "[redacted]",
        }
    )

    assert sanitized == {"secret_token": "[redacted]"}


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("secretion_score", 0.91),
        ("secretory_signal", True),
        ("secretome_count", 12),
        ("tokenCount", 42),
        ("tokenUsage", 7),
    ),
)
def test_public_diagnostic_payload_preserves_scientific_secret_prefix_words(
    key: str,
    value: object,
) -> None:
    assert sanitize_public_diagnostic_payload({key: value}) == {key: value}


def test_legacy_tool_runtime_sanitizes_handler_exception() -> None:
    def fail_handler(_context: object, _invocation: ToolInvocation) -> str:
        raise ValueError("failed at /home/operator/private.toml")

    runtime = LegacyFunctionToolRuntime(
        tool_name="example.tool",
        handler=fail_handler,
        tool_spec=ToolSpec(
            tool_name="example.tool",
            description="test",
            input_schema={"type": "object", "properties": {}},
        ),
    )
    result = runtime.dispatch(
        AgentStepContext(
            step_id="step_1",
            session_id="sess_1",
            agent_id="agent:executor",
            actor_kind="agent",
            role="executor",
            call_index=0,
        ),
        ToolInvocation(
            call_id="call_1",
            tool_name="example.tool",
            arguments={},
        ),
        object(),
    )

    assert not result.ok
    assert "/home/operator" not in result.content
    assert "[redacted-host-path]" in result.content


def test_legacy_tool_runtime_preserves_successful_scientific_string() -> None:
    content = (
        "motif label /private/AOX-reference and "
        "https://rest.uniprot.org/uniprotkb/search?query=protein_name:oxidase"
    )
    runtime = LegacyFunctionToolRuntime(
        tool_name="example.tool",
        handler=lambda _context, _invocation: content,
        tool_spec=ToolSpec(
            tool_name="example.tool",
            description="test",
            input_schema={"type": "object", "properties": {}},
        ),
    )

    result = runtime.dispatch(
        AgentStepContext(
            step_id="step_1",
            session_id="sess_1",
            agent_id="agent:executor",
            actor_kind="agent",
            role="executor",
            call_index=0,
        ),
        ToolInvocation(
            call_id="call_1",
            tool_name="example.tool",
            arguments={},
        ),
        object(),
    )

    assert result.ok
    assert result.content == content
    assert result.summary == content


def test_legacy_tool_runtime_sanitizes_structured_error_result() -> None:
    def error_handler(
        _context: object, invocation: ToolInvocation
    ) -> ToolResult:
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            content=json.dumps(
                {
                    "message": "failed at /tmp/private/state",
                    "access_token": "raw-token",
                }
            ),
            status="failed",
            summary="failed at /var/lib/private/state",
            details={"local_path": "/custom/private"},
            error_code="/home/operator/private-error-code",
            terminal_action="/tmp/private-terminal-action",
        )

    runtime = LegacyFunctionToolRuntime(
        tool_name="example.tool",
        handler=error_handler,
        tool_spec=ToolSpec(
            tool_name="example.tool",
            description="test",
            input_schema={"type": "object", "properties": {}},
        ),
    )
    result = runtime.dispatch(
        AgentStepContext(
            step_id="step_1",
            session_id="sess_1",
            agent_id="agent:executor",
            actor_kind="agent",
            role="executor",
            call_index=0,
        ),
        ToolInvocation(
            call_id="call_1",
            tool_name="example.tool",
            arguments={},
        ),
        object(),
    )

    serialized = json.dumps(result.envelope(), sort_keys=True)
    assert "/tmp/private" not in serialized
    assert "/var/lib/private" not in serialized
    assert "raw-token" not in serialized
    assert "local_path" not in serialized
    assert result.status == "failed"
    assert result.error_code == "tool_error"
    assert result.terminal_action is None
