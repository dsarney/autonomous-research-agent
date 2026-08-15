from app.agent.researcher import WEB_SEARCH_TOOL, Researcher
from app.models import CoverageAssessment, ResearchPlan, SearchResult, Source
from tests.fakes import ScriptedGateway


def test_search_uses_web_search_and_filters_sources() -> None:
    gateway = ScriptedGateway(
        [
            SearchResult(
                query="UK EV charging competitors",
                notes="Mixed quality",
                sources=[
                    Source(
                        id="tmp",
                        url="https://gov.uk/ev-charging",
                        title="Gov",
                        snippet="Official stats",
                        relevance=0.9,
                    ),
                    Source(
                        id="tmp2",
                        url="https://gov.uk/ev-charging/",
                        title="Gov dup",
                        snippet="Same page",
                        relevance=0.8,
                    ),
                    Source(
                        id="tmp3",
                        url="https://spam.example/buy",
                        title="Spam",
                        snippet="Ad",
                        relevance=0.05,
                    ),
                ],
            )
        ]
    )
    researcher = Researcher(gateway, relevance_threshold=0.35)
    result, discarded = researcher.search("UK EV charging competitors")
    assert gateway.calls[0]["tools"] == [WEB_SEARCH_TOOL]
    assert [source.url for source in result.sources] == ["https://gov.uk/ev-charging"]
    assert len(discarded) == 2


def test_assess_coverage() -> None:
    gateway = ScriptedGateway(
        [
            CoverageAssessment(
                covered_questions=["growth"],
                gaps=["competitors"],
                follow_up_queries=["UK EV charging operators market share"],
                sufficient=False,
            )
        ]
    )
    researcher = Researcher(gateway)
    plan = ResearchPlan(
        objective="Opportunity",
        sub_questions=["growth", "competitors"],
        angles=["market"],
    )
    assessment = researcher.assess(plan, [])
    assert assessment.sufficient is False
    assert assessment.follow_up_queries
