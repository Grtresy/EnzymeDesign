from __future__ import annotations

import json

from openzyme_kernel import CompositionFailureContext
from openzyme_kernel import KernelContractError
from openzyme_kernel import observe_composition_failure


def _context() -> CompositionFailureContext:
    return CompositionFailureContext(
        failure_id="failure-1",
        distribution_id="enzymedesign",
        component_id="openzyme.kernel",
        phase="manifest_verification",
        source_ref="activation-1",
        source_version="version-1",
        correlation_id="correlation-1",
        created_at="2026-08-19T04:00:00+00:00",
    )


def test_composition_failure_has_public_safe_and_private_linked_records() -> None:
    error = KernelContractError(
        "plugin_manifest_digest_mismatch",
        "manifest mismatch at /srv/private/extensions/plugin.json",
        details={
            "plugin_id": "test.plugin",
            "expected_digest": "sha256:" + "1" * 64,
            "observed_digest": "sha256:" + "2" * 64,
            "config_path": "/srv/private/extensions/plugin.json",
            "api_token": "token-super-secret",
        },
    )

    records = observe_composition_failure(error, context=_context())
    public_json = json.dumps(records.public.to_dict(), sort_keys=True)

    assert records.public.error_code == "plugin_manifest_digest_mismatch"
    assert records.public.effect_certainty.value == "no_effect"
    assert records.public.mutation_applied is False
    assert records.public.fallback_performed is False
    assert records.public.private_diagnostic_digest == records.private.record_digest
    assert records.public.facts == {
        "expected_digest": "sha256:" + "1" * 64,
        "observed_digest": "sha256:" + "2" * 64,
        "plugin_id": "test.plugin",
    }
    assert "token-super-secret" not in public_json
    assert "/srv/private" not in public_json
    assert records.private.private_context["api_token"] == "[redacted]"
    assert records.private.private_context["config_path"].startswith("/srv/private")


def test_chained_cause_is_digest_only_in_public_and_full_in_private() -> None:
    try:
        try:
            raise OSError("filesystem path /private/root was unreadable")
        except OSError as cause:
            raise KernelContractError(
                "component_manifest_read_failed",
                "component manifest could not be read",
                details={"component_id": "test.plugin"},
            ) from cause
    except KernelContractError as error:
        records = observe_composition_failure(error, context=_context())

    assert len(records.public.cause_chain) == 2
    assert set(records.public.cause_chain[0]) == {
        "type",
        "code",
        "message_digest",
    }
    assert "/private/root" not in json.dumps(records.public.to_dict())
    assert records.private.cause_chain[1]["message"].startswith("filesystem path")


def test_untyped_internal_failure_is_not_exposed_verbatim() -> None:
    records = observe_composition_failure(
        RuntimeError("credential=do-not-expose /host/private"),
        context=_context(),
    )

    assert records.public.error_code == "composition_activation_internal_error"
    assert "do-not-expose" not in json.dumps(records.public.to_dict())
    assert records.private.exception_type == "RuntimeError"
