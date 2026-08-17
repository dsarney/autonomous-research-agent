from app.agent.planner import DOCUMENT_PLANNER_INSTRUCTIONS, Planner
from app.models import ResearchPlan, UploadedDocument
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


def test_planner_includes_uploaded_document_excerpts() -> None:
    planner = Planner(ScriptedGateway([EV_PLAN]))
    document = UploadedDocument(
        id="D1",
        filename="paper.txt",
        excerpt="The authors claim charging demand is rising.",
    )
    plan = planner.create(EV_QUERY, documents=[document])
    assert plan.objective
    call = planner.gateway.calls[0]
    assert "The authors claim charging demand is rising." in call["input"]
    assert call["instructions"] == DOCUMENT_PLANNER_INSTRUCTIONS
