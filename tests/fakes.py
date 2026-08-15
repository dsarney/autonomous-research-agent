from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ScriptedGateway:
    def __init__(self, script: list[Any] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []
        self._cancel_event = None

    def bind_cancel(self, cancel_event) -> None:
        self._cancel_event = cancel_event

    def parse(
        self,
        *,
        input: str,
        text_format: type[T],
        instructions: str | None = None,
        tools: list[dict] | None = None,
    ) -> T:
        if self._cancel_event is not None and self._cancel_event.is_set():
            from app.agent.cancel import RunCancelled

            raise RunCancelled()
        self.calls.append(
            {
                "input": input,
                "text_format": text_format,
                "instructions": instructions,
                "tools": tools,
            }
        )
        if not self.script:
            raise AssertionError(
                f"No scripted response left for {text_format.__name__}"
            )
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, text_format):
            return item
        return text_format.model_validate(item)

    def close(self) -> None:
        return
