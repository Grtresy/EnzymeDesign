from __future__ import annotations

import hashlib
import re


DEFAULT_REDACTION_PATTERNS = [
    r"(?i)(password|passwd|token|secret|api[_-]?key)\s*[=:]\s*[^\s]+",
    r"(?i)Authorization:\s*Bearer\s+[^\s]+",
]


def redact_text(text: str, extra_patterns: list[str] | None = None) -> str:
    patterns = DEFAULT_REDACTION_PATTERNS + list(extra_patterns or [])
    redacted = text
    for pattern in patterns:
        redacted = re.sub(pattern, "<redacted>", redacted)
    return redacted


def bounded_text(text: str, limit: int) -> tuple[str | None, dict[str, str]]:
    if len(text) <= limit:
        return text, {}
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return None, {
        "truncated": "true",
        "bytes": str(len(text.encode("utf-8"))),
        "sha256_12": digest,
    }


def prepare_log_payload(text: str, limit: int) -> dict[str, object]:
    inline, ref = bounded_text(text, limit)
    if inline is not None:
        return {"inline": inline}
    return {"ref": ref}
