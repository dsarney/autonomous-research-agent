from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    max_iterations: int
    max_searches_per_run: int
    openai_timeout_seconds: float
    relevance_threshold: float


def load_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        max_iterations=max(1, _int_env("MAX_ITERATIONS", 3)),
        max_searches_per_run=max(1, _int_env("MAX_SEARCHES_PER_RUN", 8)),
        openai_timeout_seconds=max(1.0, _float_env("OPENAI_TIMEOUT_SECONDS", 120.0)),
        relevance_threshold=min(1.0, max(0.0, _float_env("RELEVANCE_THRESHOLD", 0.35))),
    )
