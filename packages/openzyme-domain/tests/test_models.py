from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_domain import SourceRefKind
from openzyme_domain import utc_now_iso


def test_shared_domain_enums_remain_serializable() -> None:
    assert RunStatus.RUNNING.is_terminal is False
    assert RunStatus.SUCCEEDED.is_terminal is True
    assert ArtifactKind.CODE.value == "code"
    assert ArtifactKind.RESEARCH_DOSSIER.value == "research_dossier"
    assert SourceRefKind.PAPER.value == "paper"

def test_utc_now_iso_returns_timezone_aware_timestamp() -> None:
    assert utc_now_iso().endswith("+00:00")
