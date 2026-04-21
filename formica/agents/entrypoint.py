"""Container entrypoint for caste pods.

Reads FORMICA_COMPONENT to pick the caste and runs a bounded number of ticks.
Short-lived by design - the controller spawns replacements.
"""

from __future__ import annotations

import os
import random
import signal
import sys
import time

from formica.agents.base import Agent, new_agent_id
from formica.agents.forager import Forager
from formica.agents.gc import GarbageCollector
from formica.agents.inquiline.citation_checker import CitationChecker
from formica.agents.inquiline.numeric_sanity import NumericSanityChecker
from formica.agents.scout import Scout
from formica.agents.validator import Validator
from formica.blackboard.forum import Forum
from formica.config import FormicaConfig
from formica.telemetry.logs import get_logger
from formica.telemetry.otel import setup_otel

log = get_logger(__name__)


def _agent_for(component: str, forum: Forum, cfg: FormicaConfig) -> Agent:
    aid = new_agent_id(component)
    if component == "scout":
        return Scout(agent_id=aid, caste="scout", forum=forum, config=cfg)
    if component == "forager":
        return Forager(agent_id=aid, caste="forager", forum=forum, config=cfg)
    if component == "validator":
        return Validator(agent_id=aid, caste="validator", forum=forum, config=cfg, kind="consistency")
    if component == "gc":
        return GarbageCollector(agent_id=aid, caste="gc", forum=forum, config=cfg)
    if component == "inquiline.citation":
        return CitationChecker(agent_id=aid, caste="inquiline.citation", forum=forum, config=cfg)
    if component == "inquiline.numeric":
        return NumericSanityChecker(agent_id=aid, caste="inquiline.numeric", forum=forum, config=cfg)
    raise ValueError(f"unknown component: {component}")


def _pick_focus(component: str, forum: Forum) -> str | None:
    """Pick a focus node id for this caste's tick."""
    if component == "scout":
        # Scouts should only be handed nodes that have no SubProblem children
        # yet. Otherwise we recursively decompose already-decomposed subtrees
        # (issue #13). Objectives always qualify; SubProblems qualify only when
        # no other SubProblem links to them via CHILD_OF.
        with forum._session() as s:  # noqa: SLF001
            rec = s.run(
                "MATCH (n) WHERE (n:Objective OR n:SubProblem) "
                "AND NOT (:SubProblem)-[:CHILD_OF]->(n) "
                "RETURN n.id AS id ORDER BY rand() LIMIT 1"
            ).single()
            return rec["id"] if rec else None
    if component == "forager":
        # Prefer leaf SubProblems (no SubProblem children). Foragers produce
        # Evidence on actionable leaves, not on internal decomposition nodes.
        with forum._session() as s:  # noqa: SLF001
            rec = s.run(
                "MATCH (n:SubProblem) "
                "WHERE NOT (:SubProblem)-[:CHILD_OF]->(n) "
                "RETURN n.id AS id ORDER BY rand() LIMIT 1"
            ).single()
            return rec["id"] if rec else None
    if component.startswith("validator") or component.startswith("inquiline"):
        with forum._session() as s:  # noqa: SLF001
            rec = s.run(
                "MATCH (n:Evidence) RETURN n.id AS id ORDER BY rand() LIMIT 1"
            ).single()
            return rec["id"] if rec else None
    if component == "gc":
        return None
    return None


def main() -> int:
    component = os.environ.get("FORMICA_COMPONENT", "forager")
    cfg = FormicaConfig()
    setup_otel(component, cfg)

    forum = Forum(cfg)
    max_ticks = int(os.environ.get("FORMICA_MAX_TICKS", "20"))
    tick_sleep = float(os.environ.get("FORMICA_TICK_SLEEP", "2.0"))

    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    for i in range(max_ticks):
        if stop:
            break
        agent = _agent_for(component, forum, cfg)
        agent.focus_id = _pick_focus(component, forum)
        try:
            result = agent.tick()
            log.info(
                "tick",
                extra={
                    "component": component,
                    "agent_id": agent.agent_id,
                    "action": result.action,
                    "alarm": result.alarm,
                    "focus_id": agent.focus_id,
                },
            )
        except Exception:
            log.exception("tick failed")
        time.sleep(tick_sleep + random.uniform(0, 0.5))

    forum.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
