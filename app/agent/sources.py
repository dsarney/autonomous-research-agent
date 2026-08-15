from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from app.models import Source


def normalize_url(url: str) -> str:
    raw = url.strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.rstrip("/").lower()
    path = parsed.path.rstrip("/") or ""
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            parsed.query,
            "",
        )
    )


def filter_sources(
    sources: list[Source],
    *,
    seen_urls: set[str] | None = None,
    relevance_threshold: float = 0.35,
) -> tuple[list[Source], list[Source]]:
    """Return (kept, discarded). Drops empty URLs, duplicates, and low relevance."""
    kept: list[Source] = []
    discarded: list[Source] = []
    seen = set(seen_urls or [])

    for source in sources:
        url = source.url.strip()
        key = normalize_url(url) if url else ""
        if not url or not key:
            discarded.append(
                source.model_copy(
                    update={
                        "kept": False,
                        "credibility_notes": _note(source, "Missing URL"),
                    }
                )
            )
            continue
        if key in seen:
            discarded.append(
                source.model_copy(
                    update={
                        "kept": False,
                        "credibility_notes": _note(source, "Duplicate URL"),
                    }
                )
            )
            continue
        if source.relevance < relevance_threshold:
            discarded.append(
                source.model_copy(
                    update={
                        "kept": False,
                        "credibility_notes": _note(source, "Relevance below threshold"),
                    }
                )
            )
            continue
        seen.add(key)
        kept.append(source.model_copy(update={"kept": True}))

    kept.sort(key=lambda item: item.relevance, reverse=True)
    return kept, discarded


def _note(source: Source, reason: str) -> str:
    existing = source.credibility_notes.strip()
    if existing:
        return f"{existing}; {reason}"
    return reason
