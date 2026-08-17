from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


Confidence = Literal["high", "medium", "low"]
SourceKind = Literal["web", "upload"]
RunStatus = Literal["pending", "running", "complete", "failed", "cancelled"]
StageName = Literal[
    "queued",
    "planning",
    "searching",
    "evaluating",
    "writing",
    "complete",
    "failed",
    "cancelled",
]


class PlanRequest(BaseModel):
    query: str = Field(min_length=3, max_length=4000)


class SearchRequest(BaseModel):
    query: str | None = Field(default=None, min_length=3, max_length=4000)
    sub_questions: list[str] | None = None

    @field_validator("sub_questions")
    @classmethod
    def _non_empty_questions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("sub_questions must contain at least one question")
        return cleaned


class RunRequest(BaseModel):
    query: str = Field(min_length=3, max_length=4000)
    wait: bool = False


class UploadedDocument(BaseModel):
    id: str
    filename: str
    content_type: str = ""
    char_count: int = 0
    excerpt: str = ""


class ResearchPlan(BaseModel):
    objective: str
    sub_questions: list[str]
    angles: list[str]


class Source(BaseModel):
    id: str
    url: str
    title: str
    snippet: str
    relevance: float = Field(ge=0.0, le=1.0)
    credibility_notes: str = ""
    kept: bool = True  # Set by filter_sources, not the LLM.
    kind: SourceKind = "web"

    @field_validator("url")
    @classmethod
    def _url_present(cls, value: str) -> str:
        return value.strip()


class SearchResult(BaseModel):
    query: str
    sources: list[Source] = Field(default_factory=list)
    notes: str = ""


class CoverageAssessment(BaseModel):
    covered_questions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    follow_up_queries: list[str] = Field(default_factory=list)
    sufficient: bool = False


class IterationLog(BaseModel):
    iteration: int
    searches: list[SearchResult] = Field(default_factory=list)
    discarded_sources: list[Source] = Field(default_factory=list)
    assessment: CoverageAssessment


class Finding(BaseModel):
    claim: str
    evidence: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: Confidence
    confidence_rationale: str


class Report(BaseModel):
    executive_summary: str
    findings: list[Finding] = Field(default_factory=list)
    gaps_and_risks: list[str] = Field(default_factory=list)
    bibliography: list[Source] = Field(default_factory=list)


class ProgressEvent(BaseModel):
    stage: StageName
    label: str
    detail: str = ""


class ResearchRun(BaseModel):
    id: str
    query: str
    status: RunStatus = (
        "pending"  # Lifecycle: pending/running/complete/failed/cancelled
    )
    current_stage: StageName = "queued"  # UI pipeline step; can lag status briefly
    stage_label: str = "Queued"
    error: str | None = None
    plan: ResearchPlan | None = None
    iterations: list[IterationLog] = Field(default_factory=list)
    report: Report | None = None
    documents: list[UploadedDocument] = Field(default_factory=list)
    progress: list[ProgressEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HealthResponse(BaseModel):
    status: Literal["ok"]
