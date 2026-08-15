import json
from pathlib import Path

from io import BytesIO

from docx import Document
from app.agent.export import report_to_docx, report_to_pdf
from app.agent.writer import Writer
from app.models import Finding, Report, ResearchPlan, ResearchRun, Source
from tests.fakes import ScriptedGateway

FIXTURE = Path(__file__).parent / "fixtures" / "sample_run.json"


def test_writer_emits_schema_and_keeps_source_ids() -> None:
    plan = ResearchPlan(
        objective="Assess UK EV charging opportunity",
        sub_questions=["growth", "competitors"],
        angles=["market"],
    )
    sources = [
        Source(
            id="S1",
            url="https://gov.uk/ev",
            title="Gov",
            snippet="Growth stats",
            relevance=0.9,
        ),
        Source(
            id="S2",
            url="https://cpo.example",
            title="CPO",
            snippet="Network size",
            relevance=0.8,
        ),
    ]
    scripted = Report(
        executive_summary="The market is growing but crowded.",
        findings=[
            Finding(
                claim="Public charging demand is rising",
                evidence="Official registrations increased.",
                source_ids=["S1", "missing"],
                confidence="high",
                confidence_rationale="Government statistics",
            )
        ],
        gaps_and_risks=["Grid connection delays"],
        bibliography=[],
    )
    writer = Writer(ScriptedGateway([scripted]))
    report = writer.write(
        query="UK EV charging?", plan=plan, iterations=[], sources=sources
    )
    assert report.findings[0].source_ids == ["S1"]
    assert [item.id for item in report.bibliography] == ["S1", "S2"]
    assert report.findings[0].confidence in {"high", "medium", "low"}


def test_regression_fixture_structure() -> None:
    payload = json.loads(FIXTURE.read_text())
    run = ResearchRun.model_validate(payload)
    assert run.query
    assert run.plan is not None
    assert len(run.plan.sub_questions) >= 4
    assert run.report is not None
    assert run.report.findings
    assert all(f.confidence in {"high", "medium", "low"} for f in run.report.findings)
    docx_bytes = report_to_docx(run)
    pdf_bytes = report_to_pdf(run)
    document = Document(BytesIO(docx_bytes))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Executive summary" in text
    assert "Bibliography" in text
    assert pdf_bytes.startswith(b"%PDF")
