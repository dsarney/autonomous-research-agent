from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient

from app.agent.cancel import RunCancelled
from app.agent.documents import DEFAULT_DOCUMENT_QUERY
from app.agent.orchestrator import Orchestrator
from app.agent.planner import Planner
from app.agent.researcher import Researcher
from app.agent.writer import Writer
from app.config import Settings
from app.main import app, get_orchestrator, get_settings, get_store
from app.models import (
    CoverageAssessment,
    Finding,
    Report,
    ResearchPlan,
    SearchResult,
    Source,
)
from app.store import RunStore
from tests.fakes import ScriptedGateway

SETTINGS = Settings(
    openai_api_key="test",
    openai_model="gpt-4o-mini",
    max_iterations=2,
    max_searches_per_run=4,
    openai_timeout_seconds=30,
    relevance_threshold=0.35,
    max_upload_files=5,
    max_upload_mb=10,
    max_document_chars=20_000,
    max_total_document_chars=60_000,
)


def _orchestrator(gateway: ScriptedGateway) -> Orchestrator:
    return Orchestrator(
        Planner(gateway), Researcher(gateway), Writer(gateway), SETTINGS
    )


def test_plan_endpoint() -> None:
    plan = ResearchPlan(
        objective="Assess UK EV charging",
        sub_questions=["growth", "competitors", "policy", "risks"],
        angles=["market", "competitors"],
    )
    app.dependency_overrides[get_orchestrator] = lambda: _orchestrator(
        ScriptedGateway([plan])
    )
    client = TestClient(app)
    try:
        response = client.post(
            "/research/plan", json={"query": "Is UK EV charging a good opportunity?"}
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["sub_questions"]) >= 4
    finally:
        app.dependency_overrides.clear()


def test_search_endpoint() -> None:
    result = SearchResult(
        query="UK EV policy",
        sources=[
            Source(
                id="tmp",
                url="https://gov.uk/grants",
                title="Grants",
                snippet="Grant rules",
                relevance=0.88,
            )
        ],
        notes="ok",
    )
    app.dependency_overrides[get_orchestrator] = lambda: _orchestrator(
        ScriptedGateway([result])
    )
    client = TestClient(app)
    try:
        response = client.post(
            "/research/search", json={"query": "UK EV charging grants"}
        )
        assert response.status_code == 200
        assert response.json()[0]["sources"][0]["url"] == "https://gov.uk/grants"
    finally:
        app.dependency_overrides.clear()


def test_run_wait_and_export() -> None:
    gateway = ScriptedGateway(
        [
            ResearchPlan(objective="o", sub_questions=["q1"], angles=["market"]),
            SearchResult(
                query="q1",
                sources=[
                    Source(
                        id="t",
                        url="https://example.com/a",
                        title="A",
                        snippet="s",
                        relevance=0.9,
                    )
                ],
                notes="",
            ),
            CoverageAssessment(
                covered_questions=["q1"], gaps=[], follow_up_queries=[], sufficient=True
            ),
            Report(
                executive_summary="Summary",
                findings=[
                    Finding(
                        claim="Claim",
                        evidence="Evidence",
                        source_ids=["S1"],
                        confidence="medium",
                        confidence_rationale="Limited sources",
                    )
                ],
                gaps_and_risks=["Unknown unit economics"],
                bibliography=[],
            ),
        ]
    )
    store = RunStore()
    app.dependency_overrides[get_orchestrator] = lambda: _orchestrator(gateway)
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)
    try:
        created = client.post(
            "/research/run",
            json={
                "query": "Is the UK EV market a good opportunity for a new charging company?",
                "wait": True,
            },
        )
        assert created.status_code == 200
        run = created.json()
        assert run["status"] == "complete"
        assert run["current_stage"] == "complete"
        stages = [event["stage"] for event in run["progress"]]
        assert "planning" in stages
        assert "searching" in stages
        assert "writing" in stages
        run_id = run["id"]
        polled = client.get(f"/research/{run_id}")
        assert polled.status_code == 200
        exported_docx = client.get(f"/research/{run_id}/export.docx")
        assert exported_docx.status_code == 200
        assert exported_docx.content[:2] == b"PK"
        exported_pdf = client.get(f"/research/{run_id}/export.pdf")
        assert exported_pdf.status_code == 200
        assert exported_pdf.content.startswith(b"%PDF")
        not_ready = client.get("/research/does-not-exist/export.pdf")
        assert not_ready.status_code == 404
        home = client.get("/")
        assert home.status_code == 200
        assert 'class="workspace"' in home.text
        assert 'id="progress"' in home.text
        assert 'id="stop"' in home.text
        assert 'id="documents"' in home.text
        assert 'href="/static/styles.css"' in home.text
        styles = client.get("/static/styles.css")
        assert styles.status_code == 200
        assert "--bg:" in styles.text
        script = client.get("/static/main.js")
        assert script.status_code == 200
        assert 'src="/static/main.js"' in home.text
        assert "PIPELINE" in script.text
        assert "FormData" in script.text
        stopped = client.post(f"/research/{run_id}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "complete"
    finally:
        app.dependency_overrides.clear()


def test_missing_run_is_404() -> None:
    client = TestClient(app)
    response = client.get("/research/does-not-exist")
    assert response.status_code == 404
    stopped = client.post("/research/does-not-exist/stop")
    assert stopped.status_code == 404


class BlockingGateway:
    def __init__(self) -> None:
        self.started = threading.Event()
        self._closed = False
        self._cancel_event = None

    def bind_cancel(self, cancel_event=None) -> None:
        self._cancel_event = cancel_event

    def parse(self, **kwargs):
        self.started.set()
        deadline = time.time() + 5
        while time.time() < deadline:
            if self._closed or (
                self._cancel_event is not None and self._cancel_event.is_set()
            ):
                raise RunCancelled()
            time.sleep(0.05)
        raise TimeoutError("blocking parse was not cancelled")

    def close(self) -> None:
        self._closed = True


def test_stop_cancels_a_running_job() -> None:
    gateway = BlockingGateway()
    store = RunStore()
    app.dependency_overrides[get_orchestrator] = lambda: _orchestrator(gateway)
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)
    try:
        created = client.post(
            "/research/run",
            json={"query": "Please research DRAM prices for PC gaming", "wait": False},
        )
        assert created.status_code == 200
        run_id = created.json()["id"]
        assert gateway.started.wait(timeout=2)
        stopped = client.post(f"/research/{run_id}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "cancelled"
        status = None
        for _ in range(50):
            status = client.get(f"/research/{run_id}").json()["status"]
            if status == "cancelled":
                break
            time.sleep(0.05)
        assert status == "cancelled"
    finally:
        gateway.close()
        app.dependency_overrides.clear()


SAMPLE_PAPER = Path(__file__).parent / "fixtures" / "sample_paper.txt"


def _complete_script() -> list:
    return [
        ResearchPlan(objective="o", sub_questions=["q1"], angles=["claims"]),
        SearchResult(
            query="q1",
            sources=[
                Source(
                    id="t",
                    url="https://example.com/a",
                    title="A",
                    snippet="s",
                    relevance=0.9,
                )
            ],
            notes="",
        ),
        CoverageAssessment(
            covered_questions=["q1"], gaps=[], follow_up_queries=[], sufficient=True
        ),
        Report(
            executive_summary="Summary",
            findings=[
                Finding(
                    claim="Claim",
                    evidence="Evidence",
                    source_ids=["D1", "S1"],
                    confidence="medium",
                    confidence_rationale="Upload plus web",
                )
            ],
            gaps_and_risks=["Unknown unit economics"],
            bibliography=[],
        ),
    ]


def test_run_multipart_with_document() -> None:
    gateway = ScriptedGateway(_complete_script())
    store = RunStore()
    app.dependency_overrides[get_orchestrator] = lambda: _orchestrator(gateway)
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)
    try:
        created = client.post(
            "/research/run",
            data={
                "query": "What does this paper imply for UK charging?",
                "wait": "true",
            },
            files={
                "documents": (
                    "paper.txt",
                    SAMPLE_PAPER.read_bytes(),
                    "text/plain",
                )
            },
        )
        assert created.status_code == 200
        run = created.json()
        assert run["status"] == "complete"
        assert run["documents"][0]["id"] == "D1"
        assert run["documents"][0]["filename"] == "paper.txt"
        assert run["report"]["bibliography"][0]["id"] == "D1"
        assert run["report"]["bibliography"][0]["kind"] == "upload"
        exported = client.get(f"/research/{run['id']}/export.docx")
        assert exported.status_code == 200
        assert b"upload://" not in exported.content
    finally:
        app.dependency_overrides.clear()


def test_run_queryless_document_uses_default_brief() -> None:
    gateway = ScriptedGateway(_complete_script())
    store = RunStore()
    app.dependency_overrides[get_orchestrator] = lambda: _orchestrator(gateway)
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)
    try:
        created = client.post(
            "/research/run",
            data={"query": "", "wait": "true"},
            files={"documents": ("paper.txt", SAMPLE_PAPER.read_bytes(), "text/plain")},
        )
        assert created.status_code == 200
        assert created.json()["query"] == DEFAULT_DOCUMENT_QUERY
    finally:
        app.dependency_overrides.clear()


def test_run_rejects_unsupported_and_oversize_uploads() -> None:
    store = RunStore()
    app.dependency_overrides[get_orchestrator] = lambda: _orchestrator(
        ScriptedGateway([])
    )
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)
    try:
        unsupported = client.post(
            "/research/run",
            data={"query": "What does this file say about charging?", "wait": "true"},
            files={"documents": ("photo.png", b"not-a-document", "image/png")},
        )
        assert unsupported.status_code == 422
        tiny = SETTINGS.__class__(**{**SETTINGS.__dict__, "max_upload_mb": 1})
        app.dependency_overrides[get_settings] = lambda: tiny
        oversize = client.post(
            "/research/run",
            data={"query": "What does this file say about charging?", "wait": "true"},
            files={
                "documents": (
                    "big.txt",
                    b"x" * (1024 * 1024 + 1),
                    "text/plain",
                )
            },
        )
        assert oversize.status_code == 422
    finally:
        app.dependency_overrides.clear()
