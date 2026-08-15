from openai import APITimeoutError
import httpx
import threading

from app.agent.orchestrator import Orchestrator, friendly_openai_error
from app.agent.planner import Planner
from app.agent.researcher import Researcher
from app.agent.writer import Writer
from app.config import Settings
from app.models import (
    CoverageAssessment,
    Finding,
    Report,
    ResearchPlan,
    ResearchRun,
    SearchResult,
    Source,
)
from tests.fakes import ScriptedGateway

SETTINGS = Settings(
    openai_api_key="test",
    openai_model="gpt-4o-mini",
    max_iterations=3,
    max_searches_per_run=8,
    openai_timeout_seconds=30,
    relevance_threshold=0.35,
)


def _source(url: str, relevance: float = 0.8) -> Source:
    return Source(id="tmp", url=url, title=url, snippet="evidence", relevance=relevance)


def test_orchestrator_runs_second_iteration_then_stops() -> None:
    plan = ResearchPlan(
        objective="UK EV charging opportunity",
        sub_questions=["market growth"],
        angles=["market", "competitors"],
    )
    thin = SearchResult(
        query="market growth", sources=[_source("https://a.example/1")], notes="thin"
    )
    gap = CoverageAssessment(
        covered_questions=["market growth"],
        gaps=["competitors"],
        follow_up_queries=["UK charging competitors"],
        sufficient=False,
    )
    richer = SearchResult(
        query="UK charging competitors",
        sources=[_source("https://b.example/2")],
        notes="better",
    )
    done = CoverageAssessment(
        covered_questions=["market growth", "competitors"],
        gaps=[],
        follow_up_queries=[],
        sufficient=True,
    )
    report = Report(
        executive_summary="Promising but competitive.",
        findings=[
            Finding(
                claim="Demand is growing",
                evidence="EV uptake is rising.",
                source_ids=["S1"],
                confidence="medium",
                confidence_rationale="Single market source",
            )
        ],
        gaps_and_risks=["Policy could change"],
        bibliography=[],
    )
    gateway = ScriptedGateway([plan, thin, gap, richer, done, report])
    orchestrator = Orchestrator(
        Planner(gateway), Researcher(gateway), Writer(gateway), SETTINGS
    )
    result = orchestrator.run(
        ResearchRun(id="run-1", query="Is UK EV charging a good opportunity?")
    )
    assert result.status == "complete"
    assert result.report is not None
    assert result.current_stage == "complete"
    assert [event.stage for event in result.progress][:2] == ["planning", "planning"]
    assert "searching" in {event.stage for event in result.progress}
    assert "evaluating" in {event.stage for event in result.progress}
    assert result.progress[-1].stage == "complete"
    assert len(result.iterations) == 2
    assert result.iterations[0].assessment.sufficient is False
    assert result.iterations[1].assessment.sufficient is True
    assert [call["text_format"].__name__ for call in gateway.calls] == [
        "ResearchPlan",
        "SearchResult",
        "CoverageAssessment",
        "SearchResult",
        "CoverageAssessment",
        "Report",
    ]


def test_orchestrator_stops_at_max_iterations() -> None:
    settings = SETTINGS.__class__(
        **{**SETTINGS.__dict__, "max_iterations": 2, "max_searches_per_run": 2}
    )
    plan = ResearchPlan(objective="o", sub_questions=["q1"], angles=["market"])
    search = SearchResult(
        query="q1", sources=[_source("https://c.example/1")], notes=""
    )
    not_enough = CoverageAssessment(
        covered_questions=[],
        gaps=["more"],
        follow_up_queries=["q2"],
        sufficient=False,
    )
    report = Report(
        executive_summary="Incomplete.",
        findings=[],
        gaps_and_risks=["Thin evidence"],
        bibliography=[],
    )
    gateway = ScriptedGateway([plan, search, not_enough, search, not_enough, report])
    orchestrator = Orchestrator(
        Planner(gateway), Researcher(gateway), Writer(gateway), settings
    )
    result = orchestrator.run(ResearchRun(id="run-2", query="test question here"))
    assert result.status == "complete"
    assert len(result.iterations) == 2
    assert all(item.assessment.sufficient is False for item in result.iterations)


def test_orchestrator_records_timeouts_as_failed() -> None:
    gateway = ScriptedGateway(
        [APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1"))]
    )
    orchestrator = Orchestrator(
        Planner(gateway), Researcher(gateway), Writer(gateway), SETTINGS
    )
    result = orchestrator.run(ResearchRun(id="run-3", query="timeout please happen"))
    assert result.status == "failed"
    assert result.current_stage == "failed"
    assert result.progress[0].stage == "planning"
    assert result.progress[-1].stage == "failed"
    assert "timed out" in (result.error or "").lower()


def test_friendly_timeout_message() -> None:
    message = friendly_openai_error(
        APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1"))
    )
    assert "timed out" in message.lower()


def test_orchestrator_stops_when_cancel_event_is_set() -> None:
    gateway = ScriptedGateway([])
    orchestrator = Orchestrator(
        Planner(gateway), Researcher(gateway), Writer(gateway), SETTINGS
    )
    cancel = threading.Event()
    cancel.set()
    result = orchestrator.run(
        ResearchRun(id="run-4", query="stop this research please"),
        cancel_event=cancel,
    )
    assert result.status == "cancelled"
    assert result.current_stage == "cancelled"
    assert gateway.calls == []
