"""Pydantic models for Forum nodes. These are the typed shapes of graph nodes."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Objective(BaseModel):
    """Top-level problem submitted via `formica solve`."""

    id: str
    run_id: str
    text: str
    budget_usd: float = 0.0
    timeout_seconds: int = 600
    env: str = "dev"
    region: str = "us-east-1"
    created_at: str = Field(default_factory=_now_iso)


class SubProblem(BaseModel):
    """A decomposition of an Objective or another SubProblem."""

    id: str
    text: str
    parent_id: str
    created_at: str = Field(default_factory=_now_iso)


class Evidence(BaseModel):
    """A partial solution, computation result, quote, or claim."""

    id: str
    subproblem_id: str
    content: str
    agent_id: str
    sources: list[str] = Field(default_factory=list)
    tokens_spent: int = 0
    created_at: str = Field(default_factory=_now_iso)


class Validation(BaseModel):
    """A verdict on an Evidence node."""

    id: str
    evidence_id: str
    validator_id: str
    validator_kind: str  # unit_test | consistency | citation | numeric
    verdict: str  # validated | dead_end | needs_expert
    confidence: float = 0.5
    note: str = ""
    created_at: str = Field(default_factory=_now_iso)


class Alarm(BaseModel):
    """Transient event (hallucination, tool failure, budget overrun, capacity)."""

    id: str
    cause: str
    target_id: str | None = None
    payload: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
