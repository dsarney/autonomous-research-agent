from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.agent.export import report_to_docx, report_to_pdf
from app.agent.gateway import OpenAIGateway
from app.agent.orchestrator import Orchestrator
from app.agent.planner import Planner
from app.agent.researcher import Researcher
from app.agent.sources import normalize_url
from app.agent.writer import Writer
from app.config import Settings, load_settings
from app.models import (
    HealthResponse,
    PlanRequest,
    ProgressEvent,
    ResearchPlan,
    ResearchRun,
    RunRequest,
    SearchRequest,
    SearchResult,
)
from app.store import RunStore

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Autonomous Research Agent")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
run_store = RunStore()


@lru_cache
def get_settings() -> Settings:
    return load_settings()


def get_store() -> RunStore:
    return run_store


def get_orchestrator(settings: Settings = Depends(get_settings)) -> Orchestrator:
    if not settings.openai_api_key or settings.openai_api_key == "your_openai_api_key":
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    gateway = OpenAIGateway(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        timeout=settings.openai_timeout_seconds,
    )
    return Orchestrator(
        planner=Planner(gateway),
        researcher=Researcher(
            gateway, relevance_threshold=settings.relevance_threshold
        ),
        writer=Writer(gateway),
        settings=settings,
    )


def get_planner(orchestrator: Orchestrator = Depends(get_orchestrator)) -> Planner:
    return orchestrator.planner


def get_researcher(
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> Researcher:
    return orchestrator.researcher


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.post("/research/plan", response_model=ResearchPlan)
def create_plan(
    body: PlanRequest, planner: Planner = Depends(get_planner)
) -> ResearchPlan:
    return planner.create(body.query)


@app.post("/research/search", response_model=list[SearchResult])
def search(
    body: SearchRequest,
    researcher: Researcher = Depends(get_researcher),
) -> list[SearchResult]:
    questions: list[str] = []
    if body.sub_questions:
        questions.extend(body.sub_questions)
    if body.query:
        questions.append(body.query)
    if not questions:
        raise HTTPException(status_code=422, detail="Provide query or sub_questions")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for question in questions:
        result, _discarded = researcher.search(question, seen_urls=seen)
        results.append(result)
        for source in result.sources:
            seen.add(normalize_url(source.url))
    return results


@app.post("/research/run", response_model=ResearchRun)
def start_run(
    body: RunRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    store: RunStore = Depends(get_store),
) -> ResearchRun:
    run = ResearchRun(id=str(uuid.uuid4()), query=body.query.strip(), status="pending")
    store.save(run)
    closer = getattr(orchestrator.gateway, "close", None)
    cancel_event = store.register(run.id, closer if callable(closer) else None)
    if body.wait:
        try:
            finished = orchestrator.run(
                run, on_update=store.save, cancel_event=cancel_event
            )
            return store.save(finished)
        finally:
            store.finish(run.id)

    def _worker() -> None:
        current = store.get(run.id) or run
        try:
            finished = orchestrator.run(
                current, on_update=store.save, cancel_event=cancel_event
            )
            store.save(finished)
        finally:
            store.finish(run.id)

    threading.Thread(target=_worker, daemon=True).start()
    return run


@app.post("/research/{run_id}/stop", response_model=ResearchRun)
def stop_run(run_id: str, store: RunStore = Depends(get_store)) -> ResearchRun:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    if run.status in {"complete", "failed", "cancelled"}:
        return run
    run.status = "cancelled"
    run.current_stage = "cancelled"
    run.stage_label = "Stopped"
    run.error = None
    run.progress = list(run.progress) + [
        ProgressEvent(
            stage="cancelled",
            label="Stopped",
            detail="You can edit the question and run again.",
        )
    ]
    run.updated_at = datetime.now(timezone.utc)
    store.save(run)
    store.cancel(run_id)
    return store.get(run_id) or run


@app.get("/research/{run_id}", response_model=ResearchRun)
def get_run(run_id: str, store: RunStore = Depends(get_store)) -> ResearchRun:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return run


@app.get("/research/{run_id}/export.docx")
def export_docx(run_id: str, store: RunStore = Depends(get_store)) -> Response:
    run = _run_ready_for_export(run_id, store)
    return Response(
        content=report_to_docx(run),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="research-{run_id}.docx"'
        },
    )


@app.get("/research/{run_id}/export.pdf")
def export_pdf(run_id: str, store: RunStore = Depends(get_store)) -> Response:
    run = _run_ready_for_export(run_id, store)
    return Response(
        content=report_to_pdf(run),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="research-{run_id}.pdf"'
        },
    )


def _run_ready_for_export(run_id: str, store: RunStore) -> ResearchRun:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    if run.report is None:
        raise HTTPException(status_code=409, detail="Report is not ready to export")
    return run
