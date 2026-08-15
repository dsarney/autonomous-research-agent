from __future__ import annotations

from app.agent.gateway import Gateway
from app.models import ResearchPlan

PLANNER_INSTRUCTIONS = """You are a research planner for an autonomous investigation agent.
Given a user's question or topic, produce a focused research plan.

Rules:
- objective: one sentence describing what the investigation must decide or explain.
- sub_questions: 4 to 8 specific, searchable questions that together cover the topic.
- angles: named investigation lenses such as market, competitors, policy, adoption, infrastructure, risks, or economics.
- Do not answer the user's question. Do not invent sources. Plan only.
- Prefer questions that can be checked with public web evidence.
"""


class Planner:
    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway

    def create(self, query: str) -> ResearchPlan:
        plan = self.gateway.parse(
            input=query.strip(),
            text_format=ResearchPlan,
            instructions=PLANNER_INSTRUCTIONS,
        )
        plan.sub_questions = [q.strip() for q in plan.sub_questions if q.strip()]
        plan.angles = [a.strip() for a in plan.angles if a.strip()]
        if not plan.sub_questions:
            raise RuntimeError("Planner returned no sub-questions")
        return plan
