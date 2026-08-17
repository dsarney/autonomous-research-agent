from __future__ import annotations

from app.agent.documents import format_document_context
from app.agent.gateway import Gateway
from app.models import IterationLog, Report, ResearchPlan, Source, UploadedDocument

WRITER_INSTRUCTIONS = """You are a research report writer.
Turn the investigation log into an evidence-backed report.

Rules:
- executive_summary: 1-3 paragraphs answering the original question cautiously.
- findings: distinct claims. Each must cite source_ids from the bibliography ids provided.
- confidence is high, medium, or low with a short rationale tied to source quality and agreement.
- gaps_and_risks: what remains uncertain or could invalidate the conclusion.
- bibliography: reuse the provided sources; do not invent URLs.
- If evidence is thin, say so and lower confidence. Do not fabricate facts.
"""

DOCUMENT_WRITER_INSTRUCTIONS = """You are a research report writer.
Turn the investigation log into an evidence-backed report grounded in uploaded documents.

Rules:
- executive_summary: 1-3 paragraphs answering the original question cautiously.
- Ground findings in uploaded documents (D*) first, then use web sources (S*) for corroboration, contradiction, and related work.
- findings: distinct claims. Each must cite source_ids from the bibliography ids provided.
- confidence is high, medium, or low with a short rationale tied to source quality and agreement.
- gaps_and_risks: what remains uncertain or could invalidate the conclusion.
- bibliography: reuse the provided sources; do not invent URLs or document quotations.
- If evidence is thin, say so and lower confidence. Do not fabricate facts.
"""


class Writer:
    def __init__(self, gateway: Gateway) -> None:
        self._gateway = gateway

    def write(
        self,
        *,
        query: str,
        plan: ResearchPlan,
        iterations: list[IterationLog],
        sources: list[Source],
        documents: list[UploadedDocument] | None = None,
    ) -> Report:
        iteration_text = []
        for item in iterations:
            searches = ", ".join(search.query for search in item.searches) or "none"
            iteration_text.append(
                f"Iteration {item.iteration}: searched [{searches}]; "
                f"gaps={item.assessment.gaps}; sufficient={item.assessment.sufficient}"
            )
        source_text = (
            "\n".join(
                f"- id={s.id} kind={s.kind} title={s.title} url={s.url} relevance={s.relevance:.2f} snippet={s.snippet}"
                for s in sources
            )
            or "- none"
        )
        context = format_document_context(documents)
        prompt = (
            (f"{context}\n\n" if context else "") + f"User question: {query}\n"
            f"Objective: {plan.objective}\n"
            f"Sub-questions: {plan.sub_questions}\n"
            f"Angles: {plan.angles}\n"
            f"Loop:\n" + "\n".join(iteration_text) + "\n\n"
            f"Allowed bibliography sources:\n{source_text}"
        )
        report = self._gateway.parse(
            input=prompt,
            text_format=Report,
            instructions=(
                DOCUMENT_WRITER_INSTRUCTIONS if context else WRITER_INSTRUCTIONS
            ),
        )
        allowed = {source.id: source for source in sources}
        cleaned_findings = []
        for finding in report.findings:
            # Drop citation IDs the model invented that are not in the collected map.
            ids = [sid for sid in finding.source_ids if sid in allowed]
            cleaned_findings.append(finding.model_copy(update={"source_ids": ids}))
        bibliography = (
            list(allowed.values())
            if not report.bibliography
            else [
                allowed.get(item.id, item)
                for item in report.bibliography
                if item.id in allowed or item.url
            ]
        )
        # Collected sources overwrite the model list so the bibliography cannot include hallucinated IDs.
        bibliography = sources
        return report.model_copy(
            update={"findings": cleaned_findings, "bibliography": bibliography}
        )
