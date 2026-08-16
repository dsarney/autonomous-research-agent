from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Dict

from app.models import ResearchRun


class RunStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: Dict[str, ResearchRun] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._closers: Dict[str, Callable[[], None]] = {}

    def save(self, run: ResearchRun) -> ResearchRun:
        with self._lock:
            current = self._runs.get(run.id)
            # Cancelled is terminal: a later worker save must not revive the run.
            if (
                current is not None
                and current.status == "cancelled"
                and run.status != "cancelled"
            ):
                return current
            self._runs[run.id] = run
            return run

    def get(self, run_id: str) -> ResearchRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def register(
        self, run_id: str, closer: Callable[[], None] | None = None
    ) -> threading.Event:
        event = threading.Event()
        with self._lock:
            self._cancel_events[run_id] = event
            if closer is not None:
                self._closers[run_id] = closer
        return event

    def cancel(self, run_id: str) -> bool:
        # Pop closer under the lock, then call it outside so close() cannot deadlock.
        with self._lock:
            event = self._cancel_events.get(run_id)
            closer = self._closers.pop(run_id, None)
        if event is None:
            return False
        event.set()
        if closer is not None:
            try:
                closer()
            except Exception:
                pass  # Cleanup must not mask a user stop.
        return True

    def finish(self, run_id: str) -> None:
        # Worker cleanup: close the gateway without setting the cancel event.
        with self._lock:
            self._cancel_events.pop(run_id, None)
            closer = self._closers.pop(run_id, None)
        if closer is not None:
            try:
                closer()
            except Exception:
                pass
