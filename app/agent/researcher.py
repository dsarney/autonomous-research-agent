from __future__ import annotations

from app.agent.gateway import Gateway
from app.agent.sources import filter_sources
from app.models import CoverageAssessment, ResearchPlan, SearchResult, Source

SEARCH_INSTRUCTIONS = """You are a research analyst with web search.
Search the public web for the given question.

Return:
- query: the search question you actually investigated
- sources: up to 5 distinct sources with real URLs, titles, short snippets, relevance 0-1, and credibility notes
- notes: brief commentary on evidence quality or missing data

Prefer primary sources: government, regulators, company filings, reputable news, and industry analysts.
Mark relevance honestly. Do not fabricate URLs.
"""

ASSESS_INSTRUCTIONS = """You evaluate whether collected sources cover a research plan.
Identify which sub-questions are reasonably evidenced, which gaps remain, and 0-4 follow-up search queries.
Set sufficient=true only if the main objective can be answered with the current evidence, including major risks.
Do not invent sources. Follow-up queries should be specific and searchable.
"""

WEB_SEARCH_TOOL = {"type": "web_search"}


class Researcher:
    def __init__(self, gateway: Gateway, relevance_threshold: float = 0.35) -> None:
        self._gateway = gateway
        self._relevance_threshold = relevance_threshold

    def search(
        self, query: str, *, seen_urls: set[str] | None = None
    ) -> tuple[SearchResult, list[Source]]:
        raw = self._gateway.parse(
            input=query.strip(),
            text_format=SearchResult,
            instructions=SEARCH_INSTRUCTIONS,
            tools=[WEB_SEARCH_TOOL],
        )
        kept, discarded = filter_sources(
            raw.sources,
            seen_urls=seen_urls,
            relevance_threshold=self._relevance_threshold,
        )
        return (
            SearchResult(query=raw.query or query, sources=kept, notes=raw.notes),
            discarded,
        )

    def assess(self, plan: ResearchPlan, sources: list[Source]) -> CoverageAssessment:
        source_lines = (
            "\n".join(
                f"- {item.id}: {item.title} ({item.url}) relevance={item.relevance:.2f} — {item.snippet}"
                for item in sources
            )
            or "- none"
        )
        prompt = (
            f"Objective: {plan.objective}\n"
            f"Sub-questions:\n"
            + "\n".join(f"- {q}" for q in plan.sub_questions)
            + "\n\n"
            f"Angles: {', '.join(plan.angles)}\n\n"
            f"Sources:\n{source_lines}"
        )
        assessment = self._gateway.parse(
            input=prompt,
            text_format=CoverageAssessment,
            instructions=ASSESS_INSTRUCTIONS,
        )
        assessment.follow_up_queries = [
            q.strip() for q in assessment.follow_up_queries if q.strip()
        ]
        return assessment
