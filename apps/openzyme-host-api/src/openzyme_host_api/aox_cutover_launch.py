from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any
from typing import Literal
from typing import Protocol
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from mcp_hpc_runner.server import MCPHpcServer
from openzyme_core.sandbox_runtime import EXEC_MAX_TIMEOUT_SECONDS
from openzyme_core.workflow_knowledge import default_workflow_registry
from openzyme_engines import PodmanPipelineSandboxRunner
from openzyme_engines.execution import BioProviderHttpConfig
from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_reference
from openzyme_runtime import immutable_source_tree_digest
from openzyme_runtime import is_micu_provider_url
from openzyme_runtime import LIVE_MICU_TOKEN_HARD_LIMIT
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import REPO_ROOT
from openzyme_tools import compile_hpc_tool_request
from openzyme_tools import get_hpc_tool_contract

from .aox_cutover_evidence import AOX_TOOLCHAIN_RUNTIME_CONTRACTS
from .aox_cutover_runtime_config import (
    AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID,
)
from .aox_cutover_runtime_config import AOX_CUTOVER_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
from .aox_cutover_runtime_config import AOX_CUTOVER_MAX_SIGNALS_PER_DRAIN
from .aox_cutover_runtime_config import AOX_CUTOVER_MIN_ATTEMPT_TIMEOUT_SECONDS
from .aox_cutover_runtime_config import AOX_CUTOVER_SANDBOX_EXEC_TIMEOUT_SECONDS
from .aox_cutover_runtime_config import AoxRuntimeConfigSchemaError
from .aox_cutover_runtime_config import normalize_aox_blank_world_runtime_config
from .foundation import resolve_configured_foundation_settings


EFFECTIVE_CONFIG_SCHEMA_ID = AOX_BLANK_WORLD_RUNTIME_CONFIG_SCHEMA_ID
MICU_SCENARIO = "aox_blank_world_cutover"

IDENTITY_FIELDS = frozenset(
    {
        "git_commit",
        "config_digest",
        "workflow_ref",
        "scoring_contract_digest",
        "scoring_implementation_digest",
        "image_digest",
        "sdk_digest",
    }
)
ALLOWED_PREREQUISITE_FIELDS = frozenset(
    {
        "git_commit",
        "config_digest",
        "workflow_ref",
        "image_digest",
        "sdk_digest",
        "toolchain_image_digests",
        "credential_slots",
        "ncbi_identity",
        "prompt_accessions",
    }
)
IDENTITY_PREREQUISITE_FIELDS = frozenset(
    {"git_commit", "config_digest", "workflow_ref", "image_digest", "sdk_digest"}
)
CREDENTIAL_SLOT_FIELDS = frozenset({"llm", "ncbi", "semantic_scholar", "tavily"})
TOOLCHAIN_IDS = (
    "cdhit_4.8.1.hpc_apptainer_sif:v1",
    "hmmer_3.4.hmmalign.hpc_apptainer_sif:v1",
    "hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1",
    "mafft_7.525.hpc_apptainer_sif:v1",
)
HMMALIGN_TOOLCHAIN_ID = "hmmer_3.4.hmmalign.hpc_apptainer_sif:v1"
HMMBUILD_TOOLCHAIN_ID = "hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1"
KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS = ("NP_000509.1", "NP_000549.1")
KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS = ("P68871", "P69905")
RUNNER_CONTRACT_MANIFEST_RELATIVE_PATH = Path(
    "apps/mcp-hpc-runner/src/mcp_hpc_runner/contracts/hpc_tool_contracts.json"
)
AOX_TOOLCHAIN_PIN_FIXTURE_ROOT = Path(
    "apps/mcp-hpc-runner/fixtures/hpc_tool_samples/aox_hmm"
)
_TOOLCHAIN_PIN_ORDER = ("mafft", "cd-hit", "hmmbuild", "hmmalign")
_TOOLCHAIN_RUNTIME_IDENTITY_FIELDS = frozenset(
    {
        "schema_id",
        "attestation_scope",
        "execution_mode",
        "tool_id",
        "adapter_id",
        "command_template_id",
        "runner_contract_digest",
        "image_digest",
    }
)

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_WORKFLOW_REF_PATTERN = re.compile(
    r"^workflow:[a-z0-9][a-z0-9._-]{0,127}"
    r"@[0-9]+\.[0-9]+\.[0-9]+#sha256:[0-9a-f]{64}$"
)


class AoxCutoverLaunchError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = {} if details is None else dict(details)


@dataclass(frozen=True, slots=True)
class AoxCutoverDriverConfig:
    approval_mode: Literal["auto", "chrome-once"] = "auto"
    timeout_seconds: float = AOX_CUTOVER_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    max_drains: int = 120
    max_signals_per_drain: int = AOX_CUTOVER_MAX_SIGNALS_PER_DRAIN
    max_steps_per_agent: int = 16
    browser_poll_interval_seconds: float = 0.5
    browser_approval_timeout_seconds: float = 300.0
    browser_completion_hold_seconds: float = 60.0
    browser_observation_submission_timeout_seconds: float = 180.0
    browser_observation_mode: str = "chrome_devtools_mcp_file_handoff"
    ui_dist_dir: Path = field(
        default_factory=lambda: REPO_ROOT / "apps" / "openzyme-web-ui" / "dist"
    )


@dataclass(frozen=True, slots=True)
class AoxCutoverEffectiveConfig:
    settings: OpenZymeSettings
    payload: dict[str, object]
    digest: str


@dataclass(frozen=True, slots=True)
class AoxCutoverLaunchProbes:
    checkout: Callable[[Path], str]
    workflow_ref: Callable[[], str]
    scoring_identity: Callable[[], tuple[str, str]]
    sandbox_runtime_identity: Callable[[], Mapping[str, object]]
    source_tree_digest: Callable[[Path], str]


@dataclass(frozen=True, slots=True)
class AoxCutoverLaunchSnapshot:
    effective_settings: OpenZymeSettings
    effective_config: dict[str, object]
    config_digest: str
    identity: dict[str, str]
    allowed_prerequisites: dict[str, object]
    _guard: Callable[[], None] = field(repr=False, compare=False)

    def assert_unchanged(self) -> None:
        """Fail closed if checkout or launch-effective runtime identity drifted."""

        self._guard()


class _McpHpcServer(Protocol):
    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None,
    ) -> dict[str, Any]: ...


def _canonical_digest(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _bytes_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _aox_runner_contract_expectations(repo_root: Path) -> dict[str, object]:
    manifest_path = (repo_root / RUNNER_CONTRACT_MANIFEST_RELATIVE_PATH).resolve()
    expected_path = repo_root.resolve() / RUNNER_CONTRACT_MANIFEST_RELATIVE_PATH
    if (
        manifest_path != expected_path
        or expected_path.is_symlink()
        or not expected_path.is_file()
    ):
        raise AoxCutoverLaunchError(
            "aox_launch_runner_contract_manifest_invalid",
            "AOX cutover requires the canonical runner-owned contract manifest",
        )
    try:
        raw_bytes = expected_path.read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AoxCutoverLaunchError(
            "aox_launch_runner_contract_manifest_invalid",
            "AOX runner contract manifest is not readable canonical JSON",
        ) from exc
    tools = payload.get("tools") if isinstance(payload, dict) else None
    if not isinstance(tools, list) or not all(isinstance(item, dict) for item in tools):
        raise AoxCutoverLaunchError(
            "aox_launch_runner_contract_manifest_invalid",
            "AOX runner contract manifest lacks its closed tool records",
        )
    by_tool_id = {
        str(item.get("tool_id") or ""): item
        for item in tools
        if isinstance(item, dict) and str(item.get("tool_id") or "")
    }
    expected_by_tool_id = {
        contract["tool_id"]: contract
        for contract in AOX_TOOLCHAIN_RUNTIME_CONTRACTS.values()
    }
    if any(
        sum(item.get("tool_id") == tool_id for item in tools) != 1
        for tool_id in expected_by_tool_id
    ):
        raise AoxCutoverLaunchError(
            "aox_launch_runner_contract_manifest_drift",
            "AOX runner manifest must contain exactly one record per required tool",
        )
    contracts: dict[str, dict[str, str]] = {}
    for tool_id, expected in sorted(expected_by_tool_id.items()):
        raw_contract = by_tool_id.get(tool_id)
        if (
            raw_contract is None
            or raw_contract.get("adapter_id") != expected["adapter_id"]
            or raw_contract.get("command_template_id")
            != expected["command_template_id"]
        ):
            raise AoxCutoverLaunchError(
                "aox_launch_runner_contract_manifest_drift",
                "AOX runner manifest tool, adapter, or command-template identity drifted",
                details={"tool_id": tool_id},
            )
        contracts[tool_id] = {
            "adapter_id": expected["adapter_id"],
            "command_template_id": expected["command_template_id"],
            "runner_contract_digest": _canonical_digest(raw_contract),
        }
    return {
        "schema_id": "aox_runner_contract_expectations@1",
        "manifest_digest": _bytes_digest(raw_bytes),
        "contracts": contracts,
    }


def _require_digest(value: object, *, identity: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise AoxCutoverLaunchError(
            "aox_launch_digest_invalid",
            "AOX cutover launch identity contains a malformed digest",
            details={"identity": identity},
        )
    return value


def _git(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AoxCutoverLaunchError(
            "aox_launch_git_unavailable",
            "AOX cutover could not resolve the repository checkout identity",
            details={"failure_type": type(exc).__name__},
        ) from exc
    return completed.stdout.strip()


def _probe_clean_checkout(repo_root: Path) -> str:
    resolved_root = repo_root.resolve()
    top_level = Path(_git(resolved_root, "rev-parse", "--show-toplevel")).resolve()
    if top_level != resolved_root:
        raise AoxCutoverLaunchError(
            "aox_launch_repository_root_mismatch",
            "AOX cutover launch must run against the canonical repository root",
        )
    commit = _git(resolved_root, "rev-parse", "--verify", "HEAD")
    if _GIT_COMMIT_PATTERN.fullmatch(commit) is None:
        raise AoxCutoverLaunchError(
            "aox_launch_git_commit_invalid",
            "AOX cutover checkout HEAD is not a full lowercase commit identity",
        )
    status = _git(
        resolved_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if status:
        raise AoxCutoverLaunchError(
            "aox_launch_worktree_dirty",
            "AOX cutover requires a completely clean tracked and untracked worktree",
            details={"entry_count": len(status.splitlines())},
        )
    return commit


def _probe_workflow_ref() -> str:
    registry = default_workflow_registry()
    matches = [
        manifest
        for manifest in registry.list_manifests()
        if manifest.workflow_id == "aox-hmm-live"
    ]
    if len(matches) != 1:
        raise AoxCutoverLaunchError(
            "aox_launch_workflow_ambiguous",
            "AOX cutover requires exactly one registered aox-hmm-live workflow",
            details={"match_count": len(matches)},
        )
    selection_ref = matches[0].selection_ref
    try:
        registry.resolve(selection_ref)
    except ValueError as exc:
        raise AoxCutoverLaunchError(
            "aox_launch_workflow_invalid",
            "AOX workflow manifest or knowledge identity failed resolution",
        ) from exc
    return selection_ref


def _probe_scoring_identity() -> tuple[str, str]:
    if aox_motif.CONTRACT_ID != "aox_motif_rule_score@1":
        raise AoxCutoverLaunchError(
            "aox_launch_scoring_contract_invalid",
            "AOX cutover requires aox_motif_rule_score@1",
        )
    return (
        _require_digest(
            aox_motif.CONTRACT_DIGEST,
            identity="scoring_contract_digest",
        ),
        _require_digest(
            aox_motif.IMPLEMENTATION_DIGEST,
            identity="scoring_implementation_digest",
        ),
    )


def _probe_sandbox_runtime_identity() -> Mapping[str, object]:
    preflight = PodmanPipelineSandboxRunner().preflight()
    if not preflight.ok or not isinstance(preflight.runtime_identity, dict):
        raise AoxCutoverLaunchError(
            "aox_launch_sandbox_preflight_failed",
            "AOX cutover sandbox runtime identity is unavailable",
        )
    return dict(preflight.runtime_identity)


DEFAULT_LAUNCH_PROBES = AoxCutoverLaunchProbes(
    checkout=_probe_clean_checkout,
    workflow_ref=_probe_workflow_ref,
    scoring_identity=_probe_scoring_identity,
    sandbox_runtime_identity=_probe_sandbox_runtime_identity,
    source_tree_digest=immutable_source_tree_digest,
)


def canonical_prompt_accessions() -> dict[str, list[str]]:
    return {
        "formal_ncbi": list(aox_reference.NCBI_REFERENCE_ACCESSIONS),
        "probe_ncbi": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
        "probe_uniprot": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
    }


def _credential_slots(settings: OpenZymeSettings) -> dict[str, bool]:
    return {
        "llm": settings.llm.enabled,
        "ncbi": bool(settings.research.pubmed_email),
        "semantic_scholar": bool(settings.research.semantic_scholar_api_key),
        "tavily": bool(settings.research.tavily_api_key),
    }


def _ncbi_identity_digest(settings: OpenZymeSettings) -> str:
    return _canonical_digest(
        {
            "email": str(settings.research.pubmed_email or "").strip(),
            "tool": str(settings.research.pubmed_tool or "").strip(),
        }
    )


def validate_aox_cutover_identity(
    identity: Mapping[str, object],
) -> dict[str, str]:
    fields = set(identity)
    if fields != IDENTITY_FIELDS:
        raise AoxCutoverLaunchError(
            "aox_launch_identity_schema_invalid",
            "AOX campaign identity must use the exact closed seven-field schema",
            details={
                "missing": sorted(IDENTITY_FIELDS - fields),
                "unexpected": sorted(fields - IDENTITY_FIELDS),
            },
        )
    normalized: dict[str, str] = {}
    for key in sorted(IDENTITY_FIELDS):
        value = identity[key]
        if not isinstance(value, str) or not value or value != value.strip():
            raise AoxCutoverLaunchError(
                "aox_launch_identity_value_invalid",
                "AOX campaign identity values must be canonical non-empty strings",
                details={"identity": f"identity.{key}"},
            )
        normalized[key] = value
    if _GIT_COMMIT_PATTERN.fullmatch(normalized["git_commit"]) is None:
        raise AoxCutoverLaunchError(
            "aox_launch_git_commit_invalid",
            "AOX campaign identity requires a full lowercase git commit",
        )
    if _WORKFLOW_REF_PATTERN.fullmatch(normalized["workflow_ref"]) is None:
        raise AoxCutoverLaunchError(
            "aox_launch_workflow_ref_invalid",
            "AOX campaign workflow must be a full digest-pinned selection ref",
        )
    for key in (
        "config_digest",
        "scoring_contract_digest",
        "scoring_implementation_digest",
        "image_digest",
        "sdk_digest",
    ):
        _require_digest(normalized[key], identity=f"identity.{key}")
    return normalized


def _normalize_toolchain_image_digests(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(TOOLCHAIN_IDS):
        fields = set(value) if isinstance(value, dict) else set()
        raise AoxCutoverLaunchError(
            "aox_launch_toolchain_schema_invalid",
            "AOX prerequisites require the exact four route toolchain identities",
            details={
                "missing": sorted(set(TOOLCHAIN_IDS) - fields),
                "unexpected": sorted(fields - set(TOOLCHAIN_IDS)),
            },
        )
    normalized = {
        toolchain_id: _require_digest(
            value[toolchain_id],
            identity=f"allowed_prerequisites.toolchain_image_digests.{toolchain_id}",
        )
        for toolchain_id in TOOLCHAIN_IDS
    }
    if normalized[HMMALIGN_TOOLCHAIN_ID] != normalized[HMMBUILD_TOOLCHAIN_ID]:
        raise AoxCutoverLaunchError(
            "aox_launch_hmmer_image_identity_mismatch",
            "hmmbuild and hmmalign must bind the same immutable HMMER SIF bytes",
        )
    return normalized


def validate_aox_cutover_allowed_prerequisites(
    prerequisites: Mapping[str, object],
    *,
    identity: Mapping[str, object],
) -> dict[str, object]:
    normalized_identity = validate_aox_cutover_identity(identity)
    fields = set(prerequisites)
    if fields != ALLOWED_PREREQUISITE_FIELDS:
        raise AoxCutoverLaunchError(
            "aox_launch_prerequisite_schema_invalid",
            "AOX allowed prerequisites must contain exactly all nine closed fields",
            details={
                "missing": sorted(ALLOWED_PREREQUISITE_FIELDS - fields),
                "unexpected": sorted(fields - ALLOWED_PREREQUISITE_FIELDS),
            },
        )
    mismatched_identity_fields = sorted(
        key
        for key in IDENTITY_PREREQUISITE_FIELDS
        if prerequisites.get(key) != normalized_identity[key]
    )
    if mismatched_identity_fields:
        raise AoxCutoverLaunchError(
            "aox_launch_prerequisite_identity_mismatch",
            "AOX prerequisites do not align with the campaign identity",
            details={"fields": mismatched_identity_fields},
        )
    credential_slots = prerequisites.get("credential_slots")
    if (
        not isinstance(credential_slots, dict)
        or set(credential_slots) != CREDENTIAL_SLOT_FIELDS
        or any(type(value) is not bool for value in credential_slots.values())
        or credential_slots.get("llm") is not True
        or credential_slots.get("ncbi") is not True
    ):
        raise AoxCutoverLaunchError(
            "aox_launch_credential_slots_invalid",
            "AOX prerequisites require exact boolean credential slots with LLM and NCBI ready",
        )
    ncbi_identity = _require_digest(
        prerequisites.get("ncbi_identity"),
        identity="allowed_prerequisites.ncbi_identity",
    )
    prompt_accessions = prerequisites.get("prompt_accessions")
    if prompt_accessions != canonical_prompt_accessions():
        raise AoxCutoverLaunchError(
            "aox_launch_prompt_accessions_invalid",
            "AOX prerequisites must bind the exact formal and known-positive accessions",
        )
    toolchain_image_digests = _normalize_toolchain_image_digests(
        prerequisites.get("toolchain_image_digests")
    )
    return {
        **{
            key: normalized_identity[key]
            for key in sorted(IDENTITY_PREREQUISITE_FIELDS)
        },
        "credential_slots": {
            key: credential_slots[key] for key in sorted(CREDENTIAL_SLOT_FIELDS)
        },
        "ncbi_identity": ncbi_identity,
        "prompt_accessions": canonical_prompt_accessions(),
        "toolchain_image_digests": toolchain_image_digests,
    }


def build_aox_cutover_allowed_prerequisites(
    *,
    identity: Mapping[str, object],
    settings: OpenZymeSettings,
    toolchain_image_digests: Mapping[str, object],
) -> dict[str, object]:
    normalized_identity = validate_aox_cutover_identity(identity)
    payload: dict[str, object] = {
        **{
            key: normalized_identity[key]
            for key in sorted(IDENTITY_PREREQUISITE_FIELDS)
        },
        "credential_slots": _credential_slots(settings),
        "ncbi_identity": _ncbi_identity_digest(settings),
        "prompt_accessions": canonical_prompt_accessions(),
        "toolchain_image_digests": dict(toolchain_image_digests),
    }
    return validate_aox_cutover_allowed_prerequisites(
        payload,
        identity=normalized_identity,
    )


def _safe_provider_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AoxCutoverLaunchError(
            "aox_launch_llm_endpoint_invalid",
            "AOX cutover LLM endpoint must be a public credential-free HTTP(S) URL",
        )
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    path = parsed.path.rstrip("/") or ""
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def _resolved_regular_file(path_value: str, *, repo_root: Path, identity: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    if path.is_symlink() or not path.is_file():
        raise AoxCutoverLaunchError(
            "aox_launch_config_file_invalid",
            "AOX cutover configuration must be a real regular file",
            details={"identity": identity},
        )
    return path.resolve()


def _purpose_policy_projection(settings: OpenZymeSettings) -> dict[str, object]:
    return {
        purpose: {
            "max_tokens": policy.max_tokens,
            "timeout": policy.timeout,
            "max_retries": policy.max_retries,
            "structured_output_method": policy.structured_output_method,
            "structured_output_retry_backoff_seconds": (
                policy.structured_output_retry_backoff_seconds
            ),
        }
        for purpose, policy in sorted(settings.llm.purpose_policies.items())
    }


def _validate_driver(driver: AoxCutoverDriverConfig) -> None:
    if driver.approval_mode not in {"auto", "chrome-once"}:
        raise AoxCutoverLaunchError(
            "aox_launch_approval_mode_invalid",
            "AOX cutover approval mode must be auto or chrome-once",
        )
    if driver.browser_observation_mode != "chrome_devtools_mcp_file_handoff":
        raise AoxCutoverLaunchError(
            "aox_launch_browser_observation_mode_invalid",
            "AOX cutover requires the closed Chrome DevTools MCP observation handoff",
        )
    integer_values = {
        "max_drains": driver.max_drains,
        "max_signals_per_drain": driver.max_signals_per_drain,
        "max_steps_per_agent": driver.max_steps_per_agent,
    }
    numeric_values = {
        "timeout_seconds": driver.timeout_seconds,
        "browser_poll_interval_seconds": driver.browser_poll_interval_seconds,
        "browser_approval_timeout_seconds": (driver.browser_approval_timeout_seconds),
        "browser_observation_submission_timeout_seconds": (
            driver.browser_observation_submission_timeout_seconds
        ),
    }
    invalid = sorted(
        key
        for key, value in integer_values.items()
        if type(value) is not int or value <= 0
    )
    invalid.extend(
        key
        for key, value in numeric_values.items()
        if type(value) not in {int, float}
        or not math.isfinite(float(value))
        or value <= 0
    )
    if (
        type(driver.browser_completion_hold_seconds) not in {int, float}
        or not math.isfinite(float(driver.browser_completion_hold_seconds))
        or driver.browser_completion_hold_seconds < 0
        or (
            driver.approval_mode == "chrome-once"
            and driver.browser_completion_hold_seconds <= 0
        )
    ):
        invalid.append("browser_completion_hold_seconds")
    if invalid:
        raise AoxCutoverLaunchError(
            "aox_launch_driver_bounds_invalid",
            "AOX cutover driver bounds must be positive and finite",
            details={"fields": invalid},
        )
    if driver.max_signals_per_drain != AOX_CUTOVER_MAX_SIGNALS_PER_DRAIN:
        raise AoxCutoverLaunchError(
            "aox_launch_signal_fence_invalid",
            "AOX cutover must inspect durable state after every single runtime signal",
            details={
                "expected_max_signals_per_drain": (
                    AOX_CUTOVER_MAX_SIGNALS_PER_DRAIN
                ),
                "observed_max_signals_per_drain": driver.max_signals_per_drain,
            },
        )

    hmmer_poll_timeout_seconds = float(
        BioProviderHttpConfig.from_env().hmmer_poll_timeout_seconds
    )
    timeout_hierarchy_valid = (
        hmmer_poll_timeout_seconds < AOX_CUTOVER_SANDBOX_EXEC_TIMEOUT_SECONDS
        and AOX_CUTOVER_SANDBOX_EXEC_TIMEOUT_SECONDS == EXEC_MAX_TIMEOUT_SECONDS
        and EXEC_MAX_TIMEOUT_SECONDS < AOX_CUTOVER_MIN_ATTEMPT_TIMEOUT_SECONDS
        and AOX_CUTOVER_MIN_ATTEMPT_TIMEOUT_SECONDS <= driver.timeout_seconds
    )
    if not timeout_hierarchy_valid:
        raise AoxCutoverLaunchError(
            "aox_launch_timeout_hierarchy_invalid",
            "AOX cutover timeout policy is incompatible with the sealed HMM-capable hierarchy",
            details={
                "hmmer_poll_timeout_seconds": hmmer_poll_timeout_seconds,
                "sandbox_exec_timeout_seconds": (
                    AOX_CUTOVER_SANDBOX_EXEC_TIMEOUT_SECONDS
                ),
                "sandbox_exec_max_timeout_seconds": EXEC_MAX_TIMEOUT_SECONDS,
                "minimum_timeout_seconds": AOX_CUTOVER_MIN_ATTEMPT_TIMEOUT_SECONDS,
                "timeout_seconds": float(driver.timeout_seconds),
            },
        )


def build_aox_cutover_effective_config(
    settings: OpenZymeSettings,
    *,
    driver: AoxCutoverDriverConfig,
    ledger_path: Path,
    repo_root: Path = REPO_ROOT,
    source_tree_digest: Callable[[Path], str] = immutable_source_tree_digest,
) -> AoxCutoverEffectiveConfig:
    _validate_driver(driver)
    effective = resolve_configured_foundation_settings(settings)
    resolved_root = repo_root.resolve()
    resolved_ledger = ledger_path.expanduser().resolve()
    configured_ledger = (
        Path(effective.test.live_llm.token_ledger_path).expanduser().resolve()
    )
    if configured_ledger != resolved_ledger:
        raise AoxCutoverLaunchError(
            "aox_launch_micu_ledger_mismatch",
            "AOX campaign must use the exact cumulative MICU ledger configured for the model factory",
        )
    if effective.host_api.deployment_profile != "local-dev":
        raise AoxCutoverLaunchError(
            "aox_launch_trusted_host_required",
            "AOX cutover requires the trusted local Host profile",
        )
    if effective.host_api.principals:
        raise AoxCutoverLaunchError(
            "aox_launch_local_principals_forbidden",
            "AOX trusted local cutover must not inherit shared Host principals",
        )
    if not effective.test.enable_live_e2e:
        raise AoxCutoverLaunchError(
            "aox_launch_live_e2e_disabled",
            "AOX cutover requires explicit live E2E opt-in",
        )
    if not effective.test.enable_live_llm:
        raise AoxCutoverLaunchError(
            "aox_launch_live_llm_disabled",
            "AOX cutover requires explicit live LLM opt-in",
        )
    if not effective.test.enable_live_hpc:
        raise AoxCutoverLaunchError(
            "aox_launch_live_hpc_disabled",
            "AOX cutover requires explicit live HPC opt-in",
        )
    if LIVE_MICU_TOKEN_HARD_LIMIT != 500_000_000:
        raise AoxCutoverLaunchError(
            "aox_launch_micu_limit_invalid",
            "AOX cutover requires the fixed cumulative 500M MICU ceiling",
        )
    if not effective.llm.enabled or not is_micu_provider_url(effective.llm.base_url):
        raise AoxCutoverLaunchError(
            "aox_launch_micu_not_configured",
            "AOX cutover requires a real MICU-compatible LLM configuration",
        )
    if (
        effective.execution.backend != "hpc"
        or not effective.execution.hpc_runner_config
    ):
        raise AoxCutoverLaunchError(
            "aox_launch_hpc_not_configured",
            "AOX cutover requires the real HPC execution backend and runner config",
        )
    if not effective.research.pubmed_email:
        raise AoxCutoverLaunchError(
            "aox_launch_ncbi_identity_missing",
            "AOX cutover requires the configured NCBI identity",
        )
    hpc_config_path = _resolved_regular_file(
        effective.execution.hpc_runner_config,
        repo_root=resolved_root,
        identity="execution.hpc_runner_config",
    )
    runner_contract_expectations = _aox_runner_contract_expectations(resolved_root)
    effective = replace(
        effective,
        execution=replace(
            effective.execution,
            hpc_runner_config=str(hpc_config_path),
        ),
        test=replace(
            effective.test,
            live_llm=replace(
                effective.test.live_llm,
                token_ledger_path=str(resolved_ledger),
            ),
        ),
    )
    ui_dist_digest: str | None = None
    if driver.approval_mode == "chrome-once":
        ui_root = driver.ui_dist_dir.resolve()
        if (
            driver.ui_dist_dir.is_symlink()
            or not (ui_root / "index.html").is_file()
            or any(path.is_symlink() for path in ui_root.rglob("*"))
        ):
            raise AoxCutoverLaunchError(
                "aox_launch_ui_dist_invalid",
                "Chrome-observed cutover requires a complete symlink-free built UI dist",
            )
        ui_dist_digest = _require_digest(
            source_tree_digest(ui_root),
            identity="driver.ui_dist_digest",
        )
    slots = _credential_slots(effective)
    endpoint = _safe_provider_endpoint(effective.llm.base_url)
    payload: dict[str, object] = {
        "schema_id": EFFECTIVE_CONFIG_SCHEMA_ID,
        "host": {
            "deployment_profile": effective.host_api.deployment_profile,
            "storage_profile": "single_process_sqlite",
            "background_runtime_enabled": False,
            "debug_enabled": effective.host_api.debug_enabled,
            "principal_count": 0,
        },
        "execution": {
            "backend": effective.execution.backend,
            "hpc_runner_config_digest": _bytes_digest(hpc_config_path.read_bytes()),
            "aox_runner_contract_expectations": runner_contract_expectations,
        },
        "limits": dict(effective.limits.provider_limits),
        "llm": {
            "enabled": effective.llm.enabled,
            "model": effective.llm.model,
            "base_url_endpoint": endpoint,
            "extra_body_digest": _canonical_digest(effective.llm.extra_body or {}),
            "default_headers_digest": _canonical_digest(
                effective.llm.default_headers or {}
            ),
            "use_responses_api": effective.llm.use_responses_api,
            "max_tokens": effective.llm.max_tokens,
            "timeout": effective.llm.timeout,
            "max_retries": effective.llm.max_retries,
            "temperature": effective.llm.temperature,
            "structured_output_method": effective.llm.structured_output_method,
            "structured_output_retry_backoff_seconds": (
                effective.llm.structured_output_retry_backoff_seconds
            ),
            "purpose_policies": _purpose_policy_projection(effective),
            "context_window_tokens": effective.llm.context_window_tokens,
            "default_output_tokens": effective.llm.default_output_tokens,
            "context_warn_ratio": effective.llm.context_warn_ratio,
            "context_auto_compact_ratio": effective.llm.context_auto_compact_ratio,
            "context_emergency_ratio": effective.llm.context_emergency_ratio,
            "tokenizer_enabled": effective.llm.tokenizer_enabled,
        },
        "research": {
            "max_units": effective.research.max_units,
            "allow_clarification": effective.research.allow_clarification,
            "max_research_iterations": effective.research.max_research_iterations,
            "max_react_tool_calls": effective.research.max_react_tool_calls,
            "max_concurrent_research_units": (
                effective.research.max_concurrent_research_units
            ),
            "tavily_max_results": effective.research.tavily_max_results,
            "tavily_topic": effective.research.tavily_topic,
            "tavily_timeout_seconds": effective.research.tavily_timeout_seconds,
            "mcp_enabled": True,
            "mcp_tool_allowlist": list(effective.research.mcp_tool_allowlist),
            "provider_timeout_seconds": (effective.research.provider_timeout_seconds),
            "provider_max_attempts": effective.research.provider_max_attempts,
            "credential_slots": slots,
            "ncbi_identity_digest": _ncbi_identity_digest(effective),
        },
        "tracing": {
            "enabled": effective.tracing.enabled,
            "project_name_digest": _canonical_digest(
                {"project_name": effective.tracing.project_name}
            ),
        },
        "test_opt_in": {
            "live_llm": effective.test.enable_live_llm,
            "live_tavily": effective.test.enable_live_tavily,
            "live_hpc": effective.test.enable_live_hpc,
            "live_e2e": effective.test.enable_live_e2e,
            "quality_eval": effective.test.enable_quality_eval,
            "upload_langsmith": effective.test.upload_langsmith,
        },
        "driver": {
            "scenario": MICU_SCENARIO,
            "approval_mode": driver.approval_mode,
            "browser_observation_mode": driver.browser_observation_mode,
            "timeout_seconds": driver.timeout_seconds,
            "max_drains": driver.max_drains,
            "max_signals_per_drain": driver.max_signals_per_drain,
            "max_steps_per_agent": driver.max_steps_per_agent,
            "browser_poll_interval_seconds": driver.browser_poll_interval_seconds,
            "browser_approval_timeout_seconds": (
                driver.browser_approval_timeout_seconds
            ),
            "browser_completion_hold_seconds": (driver.browser_completion_hold_seconds),
            "browser_observation_submission_timeout_seconds": (
                driver.browser_observation_submission_timeout_seconds
            ),
            "ui_dist_digest": ui_dist_digest,
            "micu_hard_limit_tokens": LIVE_MICU_TOKEN_HARD_LIMIT,
            "micu_ledger_identity_digest": _canonical_digest(
                {"ledger_path": str(resolved_ledger)}
            ),
        },
    }
    try:
        payload = normalize_aox_blank_world_runtime_config(
            payload,
            expected_runner_contracts=AOX_TOOLCHAIN_RUNTIME_CONTRACTS,
        )
    except AoxRuntimeConfigSchemaError as exc:
        raise AoxCutoverLaunchError(
            "aox_launch_effective_config_schema_invalid",
            "AOX cutover effective configuration violates its closed schema",
            details=exc.details(),
        ) from exc
    return AoxCutoverEffectiveConfig(
        settings=effective,
        payload=payload,
        digest=_canonical_digest(payload),
    )


def _resolve_actual_identity(
    *,
    repo_root: Path,
    config_digest: str,
    probes: AoxCutoverLaunchProbes,
) -> dict[str, str]:
    git_commit = probes.checkout(repo_root)
    workflow_ref = probes.workflow_ref()
    scoring_contract_digest, scoring_implementation_digest = probes.scoring_identity()
    sdk_digest = _require_digest(
        probes.source_tree_digest(repo_root / "packages" / "openzyme-pipeline" / "src"),
        identity="sdk_digest",
    )
    sandbox_identity = dict(probes.sandbox_runtime_identity())
    image_digest = _require_digest(
        sandbox_identity.get("image_digest"),
        identity="sandbox_runtime_identity.image_digest",
    )
    preflight_sdk_digest = _require_digest(
        sandbox_identity.get("pipeline_sdk_digest"),
        identity="sandbox_runtime_identity.pipeline_sdk_digest",
    )
    if preflight_sdk_digest != sdk_digest:
        raise AoxCutoverLaunchError(
            "aox_launch_sandbox_sdk_mismatch",
            "sandbox preflight Pipeline SDK differs from the checkout source tree",
        )
    return validate_aox_cutover_identity(
        {
            "git_commit": git_commit,
            "config_digest": config_digest,
            "workflow_ref": workflow_ref,
            "scoring_contract_digest": scoring_contract_digest,
            "scoring_implementation_digest": scoring_implementation_digest,
            "image_digest": image_digest,
            "sdk_digest": sdk_digest,
        }
    )


def _pin_fixture(repo_root: Path, name: str) -> Path:
    resolved_root = repo_root.resolve()
    fixture_root = resolved_root / AOX_TOOLCHAIN_PIN_FIXTURE_ROOT
    fixture = fixture_root / name
    if (
        fixture_root.is_symlink()
        or fixture.is_symlink()
        or not fixture.is_file()
        or fixture.resolve() != fixture
    ):
        raise AoxCutoverLaunchError(
            "aox_launch_toolchain_pin_fixture_invalid",
            "AOX toolchain pin requires the committed deterministic runner fixture",
            details={"fixture_id": name},
        )
    return fixture


def _pin_artifact(path: Path, *, artifact_id: str) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "storage_uri": str(path),
        "title": "AOX cutover toolchain pin fixture",
        "relative_path": path.name,
        "metadata": {
            "classification": "deterministic_fixture",
            "scientific_evidence": False,
            "purpose": "aox_cutover_toolchain_pin",
        },
    }


def _runner_expectations_by_tool_id(
    runner_contract_expectations: Mapping[str, object],
) -> dict[str, dict[str, str]]:
    contracts = runner_contract_expectations.get("contracts")
    expected_tool_ids = {
        str(contract["tool_id"])
        for contract in AOX_TOOLCHAIN_RUNTIME_CONTRACTS.values()
    }
    if not isinstance(contracts, Mapping) or set(contracts) != expected_tool_ids:
        raise AoxCutoverLaunchError(
            "aox_launch_toolchain_pin_contract_invalid",
            "AOX toolchain pin requires the exact effective runner contract closure",
        )
    normalized: dict[str, dict[str, str]] = {}
    for tool_id in sorted(expected_tool_ids):
        record = contracts[tool_id]
        if not isinstance(record, Mapping):
            raise AoxCutoverLaunchError(
                "aox_launch_toolchain_pin_contract_invalid",
                "AOX toolchain pin runner contract record is malformed",
                details={"tool_id": tool_id},
            )
        normalized[tool_id] = {
            "adapter_id": str(record.get("adapter_id") or ""),
            "command_template_id": str(record.get("command_template_id") or ""),
            "runner_contract_digest": _require_digest(
                record.get("runner_contract_digest"),
                identity=f"runner_contract.{tool_id}",
            ),
        }
    return normalized


def _compile_toolchain_pin_request(
    *,
    tool_id: str,
    artifacts: list[dict[str, object]],
    tool_inputs: Mapping[str, object] | None = None,
) -> dict[str, object]:
    artifact_ids = [str(artifact["artifact_id"]) for artifact in artifacts]
    return compile_hpc_tool_request(
        tool_id=tool_id,
        tool_inputs=dict(tool_inputs or {}),
        execution_mode="ssh",
        execution_goal={
            "purpose": "aox_cutover_toolchain_pin",
            "classification": "deterministic_fixture",
            "scientific_evidence": False,
        },
        required_artifacts=artifacts,
        context_artifacts=(),
        required_artifact_ids=artifact_ids,
        context_artifact_ids=(),
    )


def attest_aox_toolchain_image_digests(
    *,
    server: _McpHpcServer,
    repo_root: Path,
    runner_contract_expectations: Mapping[str, object],
) -> dict[str, str]:
    """Attest all AOX SIF bytes in the SSH shell that executes real payloads.

    The inputs are committed deterministic, non-scientific fixtures.  Commands
    are compiled by the production OpenZyme tool compiler and then rebound to
    the runner-owned contracts by ``MCPHpcServer``.  No configured SIF locator,
    discovery receipt, or Slurm metadata is accepted as an image identity.
    """

    expected_contracts = _runner_expectations_by_tool_id(
        runner_contract_expectations
    )
    input_sequences = _pin_fixture(repo_root, "input_sequences.fasta")
    model_alignment = _pin_fixture(repo_root, "msa.sto")
    search_targets = _pin_fixture(repo_root, "search_targets.fasta")
    hmmbuild_model: Path | None = None
    image_digests: dict[str, str] = {}

    for route_name in _TOOLCHAIN_PIN_ORDER:
        expected = AOX_TOOLCHAIN_RUNTIME_CONTRACTS[route_name]
        tool_id = str(expected["tool_id"])
        if route_name in {"mafft", "cd-hit"}:
            artifacts = [
                _pin_artifact(
                    input_sequences,
                    artifact_id=f"aox-pin-{route_name}-input",
                )
            ]
        elif route_name == "hmmbuild":
            artifacts = [
                _pin_artifact(
                    model_alignment,
                    artifact_id="aox-pin-hmmbuild-alignment",
                )
            ]
        else:
            if hmmbuild_model is None:
                raise AoxCutoverLaunchError(
                    "aox_launch_toolchain_pin_chain_invalid",
                    "AOX hmmalign pin requires the completed hmmbuild output",
                )
            artifacts = [
                _pin_artifact(
                    hmmbuild_model,
                    artifact_id="aox-pin-hmmalign-model",
                ),
                _pin_artifact(
                    search_targets,
                    artifact_id="aox-pin-hmmalign-targets",
                ),
            ]
        tool_inputs: dict[str, object] = {}
        if route_name == "cd-hit":
            tool_inputs = {"identity": 1.0, "word_size": 5}
        try:
            request = _compile_toolchain_pin_request(
                tool_id=tool_id,
                artifacts=artifacts,
                tool_inputs=tool_inputs,
            )
            result = server.call_tool(
                "exec.run",
                {
                    "runspec": request["runspec"],
                    "mode_override": "ssh",
                },
            )
        except AoxCutoverLaunchError:
            raise
        except Exception as exc:  # noqa: BLE001 - redact runner internals at boundary
            raise AoxCutoverLaunchError(
                "aox_launch_toolchain_pin_execution_failed",
                "AOX toolchain pin failed inside the trusted runner boundary",
                details={
                    "tool_id": tool_id,
                    "failure_type": type(exc).__name__,
                },
            ) from exc
        if (
            not isinstance(result, Mapping)
            or result.get("status") != "completed"
            or type(result.get("exit_code")) is not int
            or result.get("exit_code") != 0
            or result.get("selected_mode") != "ssh"
            or result.get("error_code") is not None
        ):
            raise AoxCutoverLaunchError(
                "aox_launch_toolchain_pin_execution_failed",
                "AOX toolchain pin did not complete as an authoritative SSH run",
                details={"tool_id": tool_id},
            )
        runtime_identity = result.get("toolchain_runtime_identity")
        if (
            not isinstance(runtime_identity, Mapping)
            or set(runtime_identity) != _TOOLCHAIN_RUNTIME_IDENTITY_FIELDS
        ):
            raise AoxCutoverLaunchError(
                "aox_launch_toolchain_pin_identity_missing",
                "AOX toolchain pin lacks its closed same-shell runtime identity",
                details={"tool_id": tool_id},
            )
        expected_runner = expected_contracts[tool_id]
        expected_identity = {
            "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
            "attestation_scope": "same_ssh_login_shell_pre_exec",
            "execution_mode": "ssh",
            "tool_id": tool_id,
            "adapter_id": str(expected["adapter_id"]),
            "command_template_id": str(expected["command_template_id"]),
            "runner_contract_digest": expected_runner["runner_contract_digest"],
        }
        mismatched = sorted(
            key
            for key, value in expected_identity.items()
            if runtime_identity.get(key) != value
        )
        if mismatched:
            raise AoxCutoverLaunchError(
                "aox_launch_toolchain_pin_identity_mismatch",
                "AOX toolchain pin identity differs from the effective runner contract",
                details={"tool_id": tool_id, "fields": mismatched},
            )
        image_digest = _require_digest(
            runtime_identity.get("image_digest"),
            identity=f"toolchain_runtime_identity.{tool_id}.image_digest",
        )
        contract = get_hpc_tool_contract(tool_id)
        expected_output_paths = {
            output.path for output in contract.expected_outputs
        }
        raw_artifacts = result.get("artifacts")
        if (
            not isinstance(raw_artifacts, Mapping)
            or set(raw_artifacts) != expected_output_paths
        ):
            raise AoxCutoverLaunchError(
                "aox_launch_toolchain_pin_output_invalid",
                "AOX toolchain pin did not return its exact declared output closure",
                details={"tool_id": tool_id},
            )
        materialized_outputs: dict[str, Path] = {}
        for output_path in sorted(expected_output_paths):
            local_value = raw_artifacts[output_path]
            local_path = Path(str(local_value)).expanduser()
            if local_path.is_symlink() or not local_path.is_file():
                raise AoxCutoverLaunchError(
                    "aox_launch_toolchain_pin_output_invalid",
                    "AOX toolchain pin output was not materialized as a regular file",
                    details={"tool_id": tool_id, "output_id": output_path},
                )
            materialized_outputs[output_path] = local_path.resolve()
        if route_name == "hmmbuild":
            hmmbuild_model = materialized_outputs["bio_tools/hmmbuild/model.hmm"]
        image_digests[str(expected["toolchain_id"])] = image_digest

    return _normalize_toolchain_image_digests(image_digests)


def pin_aox_cutover_launch(
    *,
    settings: OpenZymeSettings,
    driver: AoxCutoverDriverConfig,
    ledger_path: Path,
    repo_root: Path = REPO_ROOT,
    probes: AoxCutoverLaunchProbes = DEFAULT_LAUNCH_PROBES,
    runner_server_factory: Callable[[str | Path | None], _McpHpcServer] = (
        MCPHpcServer
    ),
) -> AoxCutoverLaunchSnapshot:
    """Bootstrap exact launch declarations from the actual trusted runtime."""

    resolved_root = repo_root.resolve()
    effective_config = build_aox_cutover_effective_config(
        settings,
        driver=driver,
        ledger_path=ledger_path,
        repo_root=resolved_root,
        source_tree_digest=probes.source_tree_digest,
    )
    actual_identity = _resolve_actual_identity(
        repo_root=resolved_root,
        config_digest=effective_config.digest,
        probes=probes,
    )
    try:
        server = runner_server_factory(
            effective_config.settings.execution.hpc_runner_config
        )
    except Exception as exc:  # noqa: BLE001 - private config stays behind Host
        raise AoxCutoverLaunchError(
            "aox_launch_toolchain_pin_runner_unavailable",
            "AOX toolchain pin could not initialize the trusted runner",
            details={"failure_type": type(exc).__name__},
        ) from exc
    execution_config = effective_config.payload.get("execution")
    runner_expectations = (
        execution_config.get("aox_runner_contract_expectations")
        if isinstance(execution_config, Mapping)
        else None
    )
    if not isinstance(runner_expectations, Mapping):
        raise AoxCutoverLaunchError(
            "aox_launch_toolchain_pin_contract_invalid",
            "AOX toolchain pin lacks effective runner contract expectations",
        )
    toolchain_image_digests = attest_aox_toolchain_image_digests(
        server=server,
        repo_root=resolved_root,
        runner_contract_expectations=runner_expectations,
    )
    prerequisites = build_aox_cutover_allowed_prerequisites(
        identity=actual_identity,
        settings=effective_config.settings,
        toolchain_image_digests=toolchain_image_digests,
    )
    # Deliberately go back through the exact run-live launch gate after the SSH
    # attestations.  This catches checkout/config/runtime drift caused during
    # bootstrap and proves the generated declarations require no operator guess.
    snapshot = prepare_aox_cutover_launch(
        settings=settings,
        driver=driver,
        ledger_path=ledger_path,
        declared_identity=actual_identity,
        declared_prerequisites=prerequisites,
        repo_root=resolved_root,
        probes=probes,
    )
    snapshot.assert_unchanged()
    return snapshot


def _mismatched_fields(
    expected: Mapping[str, object], actual: Mapping[str, object]
) -> list[str]:
    return sorted(
        key
        for key in set(expected) | set(actual)
        if expected.get(key) != actual.get(key)
    )


def prepare_aox_cutover_launch(
    *,
    settings: OpenZymeSettings,
    driver: AoxCutoverDriverConfig,
    ledger_path: Path,
    declared_identity: Mapping[str, object],
    declared_prerequisites: Mapping[str, object],
    repo_root: Path = REPO_ROOT,
    probes: AoxCutoverLaunchProbes = DEFAULT_LAUNCH_PROBES,
) -> AoxCutoverLaunchSnapshot:
    resolved_root = repo_root.resolve()
    normalized_declared_identity = validate_aox_cutover_identity(declared_identity)
    normalized_prerequisites = validate_aox_cutover_allowed_prerequisites(
        declared_prerequisites,
        identity=normalized_declared_identity,
    )
    effective_config = build_aox_cutover_effective_config(
        settings,
        driver=driver,
        ledger_path=ledger_path,
        repo_root=resolved_root,
        source_tree_digest=probes.source_tree_digest,
    )
    actual_identity = _resolve_actual_identity(
        repo_root=resolved_root,
        config_digest=effective_config.digest,
        probes=probes,
    )
    identity_mismatches = _mismatched_fields(
        actual_identity,
        normalized_declared_identity,
    )
    if identity_mismatches:
        raise AoxCutoverLaunchError(
            "aox_launch_identity_mismatch",
            "declared AOX campaign identity differs from the actual launch runtime",
            details={"fields": identity_mismatches},
        )
    validate_aox_cutover_allowed_prerequisites(
        normalized_prerequisites,
        identity=actual_identity,
    )
    expected_prerequisites = build_aox_cutover_allowed_prerequisites(
        identity=actual_identity,
        settings=effective_config.settings,
        toolchain_image_digests=dict(
            normalized_prerequisites["toolchain_image_digests"]
        ),
    )
    prerequisite_mismatches = _mismatched_fields(
        expected_prerequisites,
        normalized_prerequisites,
    )
    if prerequisite_mismatches:
        raise AoxCutoverLaunchError(
            "aox_launch_prerequisite_runtime_mismatch",
            "declared AOX prerequisites differ from actual launch configuration",
            details={"fields": prerequisite_mismatches},
        )

    def assert_unchanged() -> None:
        current_config = build_aox_cutover_effective_config(
            settings,
            driver=driver,
            ledger_path=ledger_path,
            repo_root=resolved_root,
            source_tree_digest=probes.source_tree_digest,
        )
        current_identity = _resolve_actual_identity(
            repo_root=resolved_root,
            config_digest=current_config.digest,
            probes=probes,
        )
        changed = _mismatched_fields(actual_identity, current_identity)
        if changed:
            raise AoxCutoverLaunchError(
                "aox_launch_snapshot_drift",
                "AOX checkout or effective runtime configuration drifted after launch",
                details={"fields": changed},
            )

    return AoxCutoverLaunchSnapshot(
        effective_settings=effective_config.settings,
        effective_config=effective_config.payload,
        config_digest=effective_config.digest,
        identity=actual_identity,
        allowed_prerequisites=expected_prerequisites,
        _guard=assert_unchanged,
    )


__all__ = [
    "ALLOWED_PREREQUISITE_FIELDS",
    "AoxCutoverDriverConfig",
    "AoxCutoverEffectiveConfig",
    "AoxCutoverLaunchError",
    "AoxCutoverLaunchProbes",
    "AoxCutoverLaunchSnapshot",
    "AoxRuntimeConfigSchemaError",
    "EFFECTIVE_CONFIG_SCHEMA_ID",
    "IDENTITY_FIELDS",
    "TOOLCHAIN_IDS",
    "attest_aox_toolchain_image_digests",
    "build_aox_cutover_allowed_prerequisites",
    "build_aox_cutover_effective_config",
    "canonical_prompt_accessions",
    "normalize_aox_blank_world_runtime_config",
    "pin_aox_cutover_launch",
    "prepare_aox_cutover_launch",
    "validate_aox_cutover_allowed_prerequisites",
    "validate_aox_cutover_identity",
]
