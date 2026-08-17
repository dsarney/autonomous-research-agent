from __future__ import annotations

from app.agent.documents import format_document_context
from app.agent.gateway import Gateway
from app.models import ResearchPlan, UploadedDocument

PLANNER_INSTRUCTIONS = """You are a research planner for an autonomous investigation agent.
Given a user's question or topic, produce a focused research plan.

Rules:
- objective: one sentence describing what the investigation must decide or explain.
- sub_questions: 4 to 8 specific, searchable questions that together cover the topic.
- angles: named investigation lenses such as market, competitors, policy, adoption, infrastructure, risks, or economics.
- Do not answer the user's question. Do not invent sources. Plan only.
- Prefer questions that can be checked with public web evidence.
"""

DOCUMENT_PLANNER_INSTRUCTIONS = """You are a research planner for an autonomous investigation agent.
The user uploaded one or more papers or articles. Plan an investigation of those documents.

Rules:
- objective: one sentence describing what the investigation must decide or explain about the uploaded work.
- sub_questions: 4 to 8 specific, web-searchable questions covering the papers' main claims, methods, related evidence, limitations, and open questions.
- angles: named investigation lenses such as claims, methods, related work, replication, policy, or risks.
- Use the uploaded text as the seed. Do not answer the question. Do not invent sources. Plan only.
- Follow-up questions must be searchable on the public web (related papers, datasets, corroboration, contradiction).
"""


class Planner:
    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway

    def create(
        self, query: str, documents: list[UploadedDocument] | None = None
    ) -> ResearchPlan:
        context = format_document_context(documents)
        prompt = query.strip()
        if context:
            prompt = f"{context}\n\nUser question: {prompt}"
        instructions = (
            DOCUMENT_PLANNER_INSTRUCTIONS if context else PLANNER_INSTRUCTIONS
        )
        plan = self.gateway.parse(
            input=prompt,
            text_format=ResearchPlan,
            instructions=instructions,
        )
        plan.sub_questions = [q.strip() for q in plan.sub_questions if q.strip()]
        plan.angles = [a.strip() for a in plan.angles if a.strip()]
        if not plan.sub_questions:
            raise RuntimeError("Planner returned no sub-questions")
        return plan
