from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import threading

from openai import APIStatusError, APITimeoutError, OpenAIError

from app.agent.cancel import RunCancelled
from app.agent.planner import Planner
from app.agent.researcher import Researcher
from app.agent.sources import normalize_url
from app.agent.writer import Writer
from app.config import Settings
from app.models import (
    IterationLog,
    ProgressEvent,
    ResearchPlan,
    ResearchRun,
    Source,
    StageName,
)

ProgressCallback = Callable[[ResearchRun], None]


def friendly_openai_error(exc: Exception) -> str:
    if isinstance(exc, APITimeoutError):
        return "The OpenAI request timed out. Try a narrower question or raise OPENAI_TIMEOUT_SECONDS."
    if isinstance(exc, APIStatusError):
        status = getattr(exc, "status_code", None)
        return f"OpenAI API error{f' ({status})' if status else ''}: {exc.message}"
    if isinstance(exc, OpenAIError):
        return f"OpenAI error: {exc}"
    return str(exc)


class Orchestrator:
    def __init__(
        self,
        planner: Planner,
        researcher: Researcher,
        writer: Writer,
        settings: Settings,
    ) -> None:
        self.planner = planner
        self.researcher = researcher
        self.writer = writer
        self.settings = settings
        self.gateway = planner.gateway

    def run(
        self,
        research_run: ResearchRun,
        on_update: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ResearchRun:
        run = research_run.model_copy(deep=True)
        run.status = "running"
        run.error = None
        bind = getattr(self.gateway, "bind_cancel", None)
        if callable(bind):
            bind(cancel_event)
        self._publish(run, "planning", "Planning the investigation", on_update)
        try:
            self._raise_if_cancelled(cancel_event)
            plan = self.planner.create(run.query)
            self._raise_if_cancelled(cancel_event)
            run.plan = plan
            self._publish(
                run,
                "planning",
                "Research plan ready",
                on_update,
                detail=f"{len(plan.sub_questions)} sub-questions",
            )
            sources, iterations = self._research_loop(
                plan, run, on_update, cancel_event
            )
            run.iterations = iterations
            self._raise_if_cancelled(cancel_event)
            self._publish(run, "writing", "Writing the report", on_update)
            run.report = self.writer.write(
                query=run.query,
                plan=plan,
                iterations=iterations,
                sources=sources,
            )
            self._raise_if_cancelled(cancel_event)
            run.status = "complete"
            self._publish(run, "complete", "Report complete", on_update)
        except RunCancelled:
            run.status = "cancelled"
            run.error = None
            self._publish(
                run,
                "cancelled",
                "Stopped",
                on_update,
                detail="You can edit the question and run again.",
            )
        except Exception as exc:
            if cancel_event is not None and cancel_event.is_set():
                run.status = "cancelled"
                run.error = None
                self._publish(
                    run,
                    "cancelled",
                    "Stopped",
                    on_update,
                    detail="You can edit the question and run again.",
                )
            else:
                run.status = "failed"
                run.error = friendly_openai_error(exc)
                self._publish(
                    run, "failed", "Research failed", on_update, detail=run.error
                )
        return run

    def _raise_if_cancelled(self, cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise RunCancelled()

    def _publish(
        self,
        run: ResearchRun,
        stage: StageName,
        label: str,
        on_update: ProgressCallback | None,
        detail: str = "",
    ) -> None:
        run.current_stage = stage
        run.stage_label = label
        run.progress.append(ProgressEvent(stage=stage, label=label, detail=detail))
        run.updated_at = datetime.now(timezone.utc)
        if on_update is not None:
            on_update(run.model_copy(deep=True))

    def _research_loop(
        self,
        plan: ResearchPlan,
        run: ResearchRun,
        on_update: ProgressCallback | None,
        cancel_event: threading.Event | None = None,
    ) -> tuple[list[Source], list[IterationLog]]:
        collected: list[Source] = []
        iterations: list[IterationLog] = []
        seen_urls: set[str] = set()
        pending = list(plan.sub_questions)
        searches_used = 0
        source_seq = 1

        for iteration in range(1, self.settings.max_iterations + 1):
            self._raise_if_cancelled(cancel_event)
            if not pending or searches_used >= self.settings.max_searches_per_run:
                break

            searches = []
            discarded: list[Source] = []
            for question in pending:
                if searches_used >= self.settings.max_searches_per_run:
                    break
                self._raise_if_cancelled(cancel_event)
                self._publish(
                    run,
                    "searching",
                    f"Searching (round {iteration})",
                    on_update,
                    detail=question,
                )
                result, dropped = self.researcher.search(question, seen_urls=seen_urls)
                self._raise_if_cancelled(cancel_event)
                searches_used += 1
                numbered = []
                for source in result.sources:
                    numbered.append(source.model_copy(update={"id": f"S{source_seq}"}))
                    source_seq += 1
                    seen_urls.add(normalize_url(source.url))
                result = result.model_copy(update={"sources": numbered})
                collected.extend(numbered)
                discarded.extend(dropped)
                searches.append(result)
                run.iterations = list(iterations)

            self._raise_if_cancelled(cancel_event)
            self._publish(
                run,
                "evaluating",
                f"Checking coverage (round {iteration})",
                on_update,
                detail=f"{len(collected)} sources so far",
            )
            assessment = self.researcher.assess(plan, collected)
            self._raise_if_cancelled(cancel_event)
            iterations.append(
                IterationLog(
                    iteration=iteration,
                    searches=searches,
                    discarded_sources=discarded,
                    assessment=assessment,
                )
            )
            run.iterations = list(iterations)
            if assessment.sufficient:
                self._publish(
                    run,
                    "evaluating",
                    "Coverage looks sufficient",
                    on_update,
                    detail="; ".join(assessment.covered_questions)
                    or "Main questions covered",
                )
                break
            pending = assessment.follow_up_queries
            if not pending:
                self._publish(
                    run,
                    "evaluating",
                    "No further searches to run",
                    on_update,
                    detail="; ".join(assessment.gaps) or "Remaining gaps noted",
                )
                break
            self._publish(
                run,
                "evaluating",
                "Gaps found; searching again",
                on_update,
                detail="; ".join(assessment.gaps)
                or f"{len(pending)} follow-up queries",
            )

        return collected, iterations
