from app.agent.sources import filter_sources, is_web_url, normalize_url
from app.models import Source


def _source(source_id: str, url: str, relevance: float) -> Source:
    return Source(
        id=source_id,
        url=url,
        title=source_id,
        snippet="snippet",
        relevance=relevance,
        credibility_notes="ok",
    )


def test_normalize_url_strips_slash_and_case() -> None:
    assert normalize_url("https://Example.com/Path/") == "https://example.com/Path"


def test_filter_drops_duplicates_low_relevance_and_empty_urls() -> None:
    sources = [
        _source("a", "https://gov.uk/ev", 0.9),
        _source("b", "https://GOV.UK/ev/", 0.8),
        _source("c", "https://blog.example/weak", 0.1),
        _source("d", "   ", 0.9),
        _source("e", "https://ft.com/charging", 0.7),
    ]
    kept, discarded = filter_sources(sources, relevance_threshold=0.35)
    assert [item.id for item in kept] == ["a", "e"]
    reasons = " ".join(item.credibility_notes for item in discarded)
    assert "Duplicate URL" in reasons
    assert "Relevance below threshold" in reasons
    assert "Missing URL" in reasons


def test_filter_ranks_by_relevance() -> None:
    sources = [
        _source("low", "https://a.example/1", 0.4),
        _source("high", "https://b.example/1", 0.95),
    ]
    kept, _discarded = filter_sources(sources)
    assert [item.id for item in kept] == ["high", "low"]


def test_is_web_url() -> None:
    assert is_web_url("https://example.com/paper")
    assert not is_web_url("upload://paper.pdf")
    assert not is_web_url("")
