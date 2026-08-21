from __future__ import annotations

from urllib.error import URLError

from openzyme_contracts import ExternalEffectCertainty
from openzyme_research import BoundedCallableClient
from openzyme_research import ResearchProviderRequest
from openzyme_research import ResearchProviderKind
from openzyme_research import ResearchUnitSpec

from openzyme_research_tavily import TavilyConfiguration
from openzyme_research_tavily import TavilyResearchProvider


DIGEST = "sha256:" + "1" * 64


def _request() -> ResearchProviderRequest:
    return ResearchProviderRequest(
        operation_id="operation-1",
        request_digest=DIGEST,
        session_id="session-1",
        unit=ResearchUnitSpec("unit-1", "enzymes", "enzyme evidence"),
        deadline_at="2026-08-19T00:00:00+00:00",
    )


def test_tavily_normalizes_source_bound_receipt_without_secret() -> None:
    provider = TavilyResearchProvider(
        configuration=TavilyConfiguration(secret_locator="secret:tavily-primary"),
        search_callable=lambda **_: {
            "results": [
                {
                    "title": "Evidence",
                    "url": "https://example.org/evidence",
                    "content": "bounded source content",
                }
            ]
        },
    )

    receipt = provider.dispatch(_request())

    assert provider.descriptor.provider_kind is ResearchProviderKind.WEB
    assert provider.descriptor.provider_id == provider.provider_id
    assert receipt.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert receipt.sources[0].locator == "https://example.org/evidence"
    assert "secret:tavily-primary" not in str(receipt.to_dict())
    assert receipt.fallback_performed is False


def test_tavily_lost_response_is_not_retried_or_replaced() -> None:
    calls = 0

    def lose_response(**_: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise URLError("response lost")

    provider = TavilyResearchProvider(
        configuration=TavilyConfiguration(secret_locator="secret:tavily-primary"),
        search_callable=lose_response,
        callable_client=BoundedCallableClient(max_attempts=1),
    )

    receipt = provider.dispatch(_request())

    assert calls == 1
    assert receipt.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert receipt.sources == ()
    assert provider.reconcile(receipt.operation_id) == receipt
    assert calls == 1
