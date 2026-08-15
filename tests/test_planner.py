from app.agent.planner import Planner
from app.models import ResearchPlan
from tests.fakes import ScriptedGateway

EV_QUERY = (
    "Is the UK electric vehicle market a good opportunity for a new charging company?"
)

EV_PLAN = ResearchPlan(
    objective="Assess whether the UK EV charging market is an attractive entry opportunity.",
    sub_questions=[
        "How fast is UK EV adoption growing?",
        "Who are the main public charging competitors?",
        "What UK government incentives and regulations apply?",
        "Is charging infrastructure keeping up with vehicle sales?",
        "What are the main commercial risks for a new charging company?",
    ],
    angles=["market", "competitors", "policy", "infrastructure", "risks"],
)


def test_planner_returns_structured_plan() -> None:
    planner = Planner(ScriptedGateway([EV_PLAN]))
    plan = planner.create(EV_QUERY)
    assert plan.objective
    assert len(plan.sub_questions) >= 4
    assert "competitors" in plan.angles
    assert "risks" in plan.angles
