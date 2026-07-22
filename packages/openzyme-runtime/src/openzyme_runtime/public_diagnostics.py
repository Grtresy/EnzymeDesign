from __future__ import annotations

from ipaddress import ip_address
import re
import socket
from urllib.parse import urlsplit
from urllib.parse import urlunsplit


_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_AUTHORIZATION_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:[A-Za-z0-9]+[_-])*"
    r"(?:authorization|cookie|set[_-]?cookie)\s*[:=]\s*[^\r\n]+"
)
_KEY_VALUE_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?P<key>[A-Za-z][A-Za-z0-9_-]{0,127})"
    r"\s*[=:]\s*(?P<value>[^\s&,]+)"
)
_HTTP_URL_PATTERN = re.compile(r"(?i)https?://[^\s\"'<>]+")
_RAW_SECRET_PATTERN = re.compile(
    r"(?i)(?:\bsk-(?:ant-)?[A-Za-z0-9_-]{12,}|"
    r"\bgh[pousr]_[A-Za-z0-9]{20,}|"
    r"\bAKIA[0-9A-Z]{16}|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
)
_PRIVATE_LOCATOR_PATTERN = re.compile(
    r"(?i)(?:storage|s3|gs|gcs|azure|ssh|scp|postgres|postgresql|redis|"
    r"mongodb(?:\+srv)?|mysql|mariadb|amqp|amqps)://[^\s\"'<>]*"
)
_CREDENTIAL_URI_PATTERN = re.compile(
    r"(?i)(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://"
    r"[^\s/@:]*:[^\s/@]*@[^\s\"'<>]*"
)
_JSON_ESCAPED_LOCATOR_PATTERN = re.compile(
    r"(?i)(?:https?|storage|s3|gs|gcs|azure|ssh|scp|file|postgres|"
    r"postgresql|redis|mongodb(?:\+srv)?|mysql|mariadb|amqp|amqps):"
    r"(?:\\/){2}[^\s\"'<>]*"
)
_PRIVATE_LOCATION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._-])(?:"
    r"/(?:app|bin|boot|cluster|code|data|dev|etc|gpfs|home|lib|lib64|lustre|"
    r"media|mnt|nix|opt|private|proc|project|root|run|sbin|scratch|snap|srv|"
    r"sys|tmp|usr|var|Users)"
    r"(?=$|[/\s\"'<>:;,()])[^\s\"'<>]*|"
    r"[A-Za-z]:[\\/][^\s\"'<>]*|"
    r"\\\\[A-Za-z0-9_.-]+\\[^\s\"'<>]*|"
    r"file://[^\s\"'<>]*|"
    r"~/[^\s\"'<>]*"
    r")"
)
_JSON_ESCAPED_PRIVATE_LOCATION_PATTERN = re.compile(
    r"(?i)\\/(?:app|cluster|code|data|etc|gpfs|home|lustre|mnt|opt|private|"
    r"project|root|run|scratch|srv|tmp|usr|var|Users)\\/[^\s\"'<>]*"
)
_PERCENT_ENCODED_PRIVATE_LOCATION_PATTERN = re.compile(
    r"(?i)%2f(?:app|cluster|code|data|etc|gpfs|home|lustre|mnt|opt|private|"
    r"project|root|run|scratch|srv|tmp|usr|var|Users)%2f[^\s\"'<>]*"
)
_MACHINE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._:@-]{0,127}$")
_CAMEL_CASE_BOUNDARY_PATTERN = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_CREDENTIAL_KEY_ALIASES = frozenset(
    {
        "accountkey",
        "aws_secret_access_key",
        "aws_secret_key",
        "azure_storage_connection_string",
        "database_url",
        "google_application_credentials",
        "mysql_pwd",
        "pgpassword",
        "rediscli_auth",
        "secret_key",
    }
)
_SAFE_SENSITIVE_METADATA_KEYS = frozenset(
    {
        "credential_slots",
        "credential_count",
        "credential_present",
        "credentials_ready",
        "token_count",
        "token_limit",
        "token_usage",
    }
)
_CREDENTIAL_KEY_COMPACT_ALIASES = frozenset(
    key.replace("_", "") for key in _CREDENTIAL_KEY_ALIASES
)

_SENSITIVE_PAYLOAD_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "host_path",
        "local_path",
        "password",
        "passwd",
        "private_key",
        "private_locator",
        "refresh_token",
        "remote_path",
        "runner_config",
        "set_cookie",
        "secret",
        "source_uri",
        "storage_uri",
        "token",
    }
)
_STRICT_PRIVATE_PAYLOAD_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "host_path",
        "password",
        "passwd",
        "refresh_token",
        "remote_path",
        "secret",
        "source_uri",
        "storage_uri",
    }
)
_REDACTED_VALUES = frozenset(
    {
        "[host_path]",
        "[redacted]",
        "[redacted-authorization]",
        "[redacted-credential]",
        "[redacted-host-path]",
        "[redacted-private-diagnostic]",
        "[redacted-private-locator]",
        "[redacted-private-url]",
        "[redacted-secret]",
    }
)


def _normalized_payload_key(value: object) -> str:
    separated = _CAMEL_CASE_BOUNDARY_PATTERN.sub("_", str(value).strip())
    return separated.casefold().replace("-", "_")


def _sensitive_payload_key(value: object) -> bool:
    normalized = _normalized_payload_key(value)
    compact = normalized.replace("_", "")
    if normalized in _SAFE_SENSITIVE_METADATA_KEYS or normalized.endswith(
        (
            "_credential_count",
            "_credential_present",
            "_credentials_ready",
            "_token_count",
            "_token_limit",
            "_token_usage",
        )
    ):
        return False
    return (
        normalized in _SENSITIVE_PAYLOAD_KEYS
        or normalized in _CREDENTIAL_KEY_ALIASES
        or compact in _CREDENTIAL_KEY_COMPACT_ALIASES
        or normalized.endswith(
            (
                "_access_token",
                "_api_key",
                "_client_secret",
                "_credential",
                "_credentials",
                "_host_path",
                "_local_path",
                "_password",
                "_private_key",
                "_private_locator",
                "_refresh_token",
                "_remote_path",
                "_runner_config",
                "_secret",
                "_secret_data",
                "_secret_file",
                "_secret_value",
                "_token",
                "_cookie",
                "_authorization",
                "_source_uri",
                "_storage_uri",
            )
        )
        or any(
            marker in normalized
            for marker in (
                "api_key",
                "apikey",
                "client_secret",
                "connection_string",
                "credential",
                "password",
                "private_key",
            )
        )
        or compact.endswith(
            (
                "accesstoken",
                "apikey",
                "authorization",
                "clientsecret",
                "connectionstring",
                "cookie",
                "credential",
                "credentials",
                "hostpath",
                "localpath",
                "password",
                "privatekey",
                "privatelocator",
                "refreshtoken",
                "remotepath",
                "runnerconfig",
                "secret",
                "sourceuri",
                "storageuri",
                "token",
            )
        )
    )


def _sanitize_key_value(match: re.Match[str]) -> str:
    if _sensitive_payload_key(match.group("key")):
        return "[redacted-credential]"
    return match.group(0)


def _contains_sensitive_key_value(value: str) -> bool:
    return any(
        _sensitive_payload_key(match.group("key"))
        for match in _KEY_VALUE_PATTERN.finditer(value)
    )


def _sanitize_json_escaped_locator(match: re.Match[str]) -> str:
    return sanitize_public_diagnostic_text(match.group(0).replace(r"\/", "/"))


def _sanitize_http_url(match: re.Match[str]) -> str:
    value = match.group(0)
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port
    except ValueError:
        return "[redacted-private-url]"
    if not hostname:
        return "[redacted-private-url]"
    try:
        address = ip_address(hostname)
    except ValueError:
        try:
            address = ip_address(socket.inet_aton(hostname))
        except OSError:
            address = None
    numeric_hostname = bool(hostname) and all(
        part.isdigit() for part in hostname.split(".")
    )
    if (
        hostname in {"localhost", "localhost.localdomain"}
        or hostname.endswith(
            (
                ".localhost",
                ".local",
                ".internal",
                ".corp",
                ".lan",
                ".home.arpa",
                ".cluster",
                ".svc",
                ".consul",
                ".test",
                ".invalid",
                ".example",
            )
        )
        or (numeric_hostname and address is None)
        or (address is None and "." not in hostname)
        or hostname.endswith((".nip.io", ".sslip.io", ".xip.io"))
        or (
            address is not None
            and (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            )
        )
    ):
        return "[redacted-private-url]"
    host_part = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host_part if port is None else f"{host_part}:{port}"
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            netloc,
            parsed.path or "/",
            "",
            "",
        )
    )


def safe_public_machine_identifier(
    value: object,
    *,
    fallback: str | None,
) -> str | None:
    """Return a bounded public machine identifier or a caller-owned fallback."""

    if value is None:
        return fallback
    candidate = str(value).strip()
    if (
        _MACHINE_IDENTIFIER_PATTERN.fullmatch(candidate) is None
        or sanitize_public_diagnostic_text(candidate) != candidate
    ):
        return fallback
    return candidate


def sanitize_public_diagnostic_text(
    value: object,
    *,
    path_replacements: tuple[tuple[str, str], ...] = (),
) -> str:
    """Return bounded-surface diagnostic text without private locations or secrets.

    Caller-provided replacements map known Host-owned locations to useful logical
    identities such as ``/workspace`` before the remaining private-location
    corpus is redacted. The function is deterministic and idempotent.
    """

    sanitized = str(value)
    for private_path, public_path in sorted(
        path_replacements,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if private_path:
            sanitized = re.sub(
                rf"(?<![/A-Za-z0-9._-]){re.escape(private_path)}"
                r"(?=$|[/\\\s\"'<>:;,()])",
                lambda _match: public_path,
                sanitized,
            )
    sanitized = _JSON_ESCAPED_LOCATOR_PATTERN.sub(
        _sanitize_json_escaped_locator,
        sanitized,
    )
    sanitized = _AUTHORIZATION_PATTERN.sub("[redacted-authorization]", sanitized)
    sanitized = _BEARER_PATTERN.sub("Bearer [redacted]", sanitized)
    sanitized = _KEY_VALUE_PATTERN.sub(_sanitize_key_value, sanitized)
    sanitized = _RAW_SECRET_PATTERN.sub("[redacted-secret]", sanitized)
    sanitized = _CREDENTIAL_URI_PATTERN.sub(
        "[redacted-private-locator]",
        sanitized,
    )
    sanitized = _HTTP_URL_PATTERN.sub(_sanitize_http_url, sanitized)
    sanitized = _PRIVATE_LOCATOR_PATTERN.sub("[redacted-private-locator]", sanitized)
    sanitized = _JSON_ESCAPED_PRIVATE_LOCATION_PATTERN.sub(
        "[redacted-host-path]",
        sanitized,
    )
    sanitized = _PERCENT_ENCODED_PRIVATE_LOCATION_PATTERN.sub(
        "[redacted-host-path]",
        sanitized,
    )
    sanitized = _PRIVATE_LOCATION_PATTERN.sub("[redacted-host-path]", sanitized)
    if (
        _AUTHORIZATION_PATTERN.search(sanitized)
        or _BEARER_PATTERN.search(sanitized)
        or _contains_sensitive_key_value(sanitized)
        or _RAW_SECRET_PATTERN.search(sanitized)
        or _CREDENTIAL_URI_PATTERN.search(sanitized)
        or _PRIVATE_LOCATOR_PATTERN.search(sanitized)
        or _JSON_ESCAPED_PRIVATE_LOCATION_PATTERN.search(sanitized)
        or _PERCENT_ENCODED_PRIVATE_LOCATION_PATTERN.search(sanitized)
        or _PRIVATE_LOCATION_PATTERN.search(sanitized)
    ):
        return "[redacted-private-diagnostic]"
    return sanitized


def sanitize_public_diagnostic_payload(value: object) -> object:
    """Recursively sanitize strings in a public diagnostic payload."""

    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized_key = _normalized_payload_key(key_text)
            if normalized_key in _STRICT_PRIVATE_PAYLOAD_KEYS:
                continue
            if _sensitive_payload_key(key):
                if not (
                    isinstance(item, str)
                    and item.strip().casefold() in _REDACTED_VALUES
                ):
                    continue
                sanitized[key_text] = item
                continue
            public_key = sanitize_public_diagnostic_text(key_text)
            if public_key != key_text:
                continue
            sanitized[public_key] = sanitize_public_diagnostic_payload(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_public_diagnostic_payload(item) for item in value]
    if isinstance(value, str):
        return sanitize_public_diagnostic_text(value)
    return value


__all__ = [
    "safe_public_machine_identifier",
    "sanitize_public_diagnostic_payload",
    "sanitize_public_diagnostic_text",
]
