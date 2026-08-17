from __future__ import annotations

from app.agent.documents import SEARCH_CONTEXT_CHARS, format_document_context
from app.agent.gateway import Gateway
from app.agent.sources import filter_sources
from app.models import (
    CoverageAssessment,
    ResearchPlan,
    SearchResult,
    Source,
    UploadedDocument,
)

SEARCH_INSTRUCTIONS = """You are a research analyst with web search.
Search the public web for the given question.

Return:
- query: the search question you actually investigated
- sources: up to 5 distinct sources with real URLs, titles, short snippets, relevance 0-1, and credibility notes
- notes: brief commentary on evidence quality or missing data

Prefer primary sources: government, regulators, company filings, reputable news, and industry analysts.
Mark relevance honestly. Do not fabricate URLs.
"""

DOCUMENT_SEARCH_INSTRUCTIONS = """You are a research analyst with web search.
The user uploaded papers or articles. Search the public web for evidence related to the given question and those documents.

Return:
- query: the search question you actually investigated
- sources: up to 5 distinct sources with real URLs, titles, short snippets, relevance 0-1, and credibility notes
- notes: brief commentary on evidence quality or missing data

Prefer related papers, datasets, official statistics, and reputable analysis that corroborates, contradicts, or contextualizes the uploaded work.
Mark relevance honestly. Do not fabricate URLs. Do not treat upload:// identifiers as web URLs.
"""

ASSESS_INSTRUCTIONS = """You evaluate whether collected sources cover a research plan.
Identify which sub-questions are reasonably evidenced, which gaps remain, and 0-4 follow-up search queries.
Set sufficient=true only if the main objective can be answered with the current evidence, including major risks.
Do not invent sources. Follow-up queries should be specific and searchable.
"""

DOCUMENT_ASSESS_INSTRUCTIONS = """You evaluate whether collected sources cover a research plan.
Sources with ids D* are user-uploaded documents and count as primary evidence for what those papers claim.
Identify which sub-questions are reasonably evidenced, which gaps remain, and 0-4 follow-up web search queries.
Set sufficient=true only if the main objective can be answered with the current evidence, including major risks.
Use follow-up queries for external corroboration, related work, and remaining gaps. Do not invent sources.
"""

WEB_SEARCH_TOOL = {"type": "web_search"}


class Researcher:
    def __init__(self, gateway: Gateway, relevance_threshold: float = 0.35) -> None:
        self._gateway = gateway
        self._relevance_threshold = relevance_threshold

    def search(
        self,
        query: str,
        *,
        seen_urls: set[str] | None = None,
        documents: list[UploadedDocument] | None = None,
    ) -> tuple[SearchResult, list[Source]]:
        context = format_document_context(
            documents, max_chars_each=SEARCH_CONTEXT_CHARS
        )
        prompt = query.strip()
        if context:
            prompt = (
                f"{context}\n\nSearch question: {prompt}\n"
                "Search the web for evidence related to this question and the uploaded documents "
                "(claims, authors, datasets, related work, replication, or contradiction)."
            )
        raw = self._gateway.parse(
            input=prompt,
            text_format=SearchResult,
            instructions=(
                DOCUMENT_SEARCH_INSTRUCTIONS if context else SEARCH_INSTRUCTIONS
            ),
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

    def assess(
        self,
        plan: ResearchPlan,
        sources: list[Source],
        documents: list[UploadedDocument] | None = None,
    ) -> CoverageAssessment:
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
        has_uploads = bool(documents) or any(item.kind == "upload" for item in sources)
        assessment = self._gateway.parse(
            input=prompt,
            text_format=CoverageAssessment,
            instructions=(
                DOCUMENT_ASSESS_INSTRUCTIONS if has_uploads else ASSESS_INSTRUCTIONS
            ),
        )
        assessment.follow_up_queries = [
            q.strip() for q in assessment.follow_up_queries if q.strip()
        ]
        return assessment
