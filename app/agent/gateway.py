from __future__ import annotations

import threading
from typing import Protocol, TypeVar

import httpx2
from openai import OpenAI
from pydantic import BaseModel

from app.agent.cancel import RunCancelled

T = TypeVar("T", bound=BaseModel)


class Gateway(Protocol):
    def parse(
        self,
        *,
        input: str,
        text_format: type[T],
        instructions: str | None = None,
        tools: list[dict] | None = None,
    ) -> T: ...

    def close(self) -> None: ...

    def bind_cancel(self, cancel_event: threading.Event | None) -> None: ...


class OpenAIGateway:
    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.model = model
        self._closed = False
        self._cancel_event: threading.Event | None = None
        self._lock = threading.Lock()
        self._http = httpx2.Client(timeout=timeout)
        self.client = OpenAI(api_key=api_key, http_client=self._http, timeout=timeout)

    def bind_cancel(self, cancel_event: threading.Event | None) -> None:
        self._cancel_event = cancel_event

    def parse(
        self,
        *,
        input: str,
        text_format: type[T],
        instructions: str | None = None,
        tools: list[dict] | None = None,
    ) -> T:
        self._raise_if_cancelled()
        kwargs: dict = {
            "model": self.model,
            "input": input,
            "text_format": text_format,
        }
        if instructions:
            kwargs["instructions"] = instructions
        if tools:
            kwargs["tools"] = tools

        box: dict = {}

        # Run the blocking parse on a daemon thread so we can poll cancel and
        # close() the HTTP client mid-request.
        def worker() -> None:
            try:
                box["response"] = self.client.responses.parse(**kwargs)
            except Exception as exc:
                box["error"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while thread.is_alive():
            if self._cancelled:
                self.close()
                raise RunCancelled()
            thread.join(timeout=0.1)

        self._raise_if_cancelled()
        if "error" in box:
            raise box["error"]
        parsed = box["response"].output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no structured output")
        return parsed

    @property
    def _cancelled(self) -> bool:
        # True if the user stopped the run or the gateway was already closed.
        return self._closed or (
            self._cancel_event is not None and self._cancel_event.is_set()
        )

    def _raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise RunCancelled()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self.client.close()
        except Exception:
            pass
        try:
            self._http.close()
        except Exception:
            pass
