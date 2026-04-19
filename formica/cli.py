"""Formica CLI.

Usage: formica solve "<problem>" --budget <usd> --timeout <s> --env <env> --region <region>
"""

from __future__ import annotations

import json
import time
import uuid

import click

from formica.blackboard.forum import Forum, new_id
from formica.blackboard.models import Objective
from formica.config import FormicaConfig
from formica.telemetry.logs import get_logger
from formica.telemetry.otel import get_tracer, setup_otel

log = get_logger(__name__)


@click.group()
def main() -> None:
    """Formica — stigmergic multi-agent problem solving."""


@main.command()
@click.argument("problem")
@click.option("--budget", type=float, default=1.0, help="Dollar budget for the run.")
@click.option("--timeout", type=int, default=600, help="Overall timeout in seconds.")
@click.option("--env", default="dev", show_default=True)
@click.option("--region", default="us-east-1", show_default=True)
@click.option("--n-solutions", type=int, default=3, help="Distinct validated solutions to wait for.")
@click.option("--stream/--no-stream", default=True, help="Stream validated evidence to stdout.")
@click.option(
    "--local/--no-local",
    default=False,
    help="Run the tick loop in-process (no Kubernetes controller needed). "
    "Use this for single-box GPU testing via docker compose.",
)
@click.option(
    "--local-tick-seconds",
    type=float,
    default=3.0,
    show_default=True,
    help="Seconds between in-process ticks when --local is set.",
)
def solve(problem: str, budget: float, timeout: int, env: str, region: str,
          n_solutions: int, stream: bool, local: bool,
          local_tick_seconds: float) -> None:
    """Submit an Objective to the Forum and wait for validated Evidence."""
    cfg = FormicaConfig(env=env, region=region)
    setup_otel("cli", cfg)
    tracer = get_tracer("formica.cli")

    run_id = uuid.uuid4().hex
    with tracer.start_as_current_span("formica.solve") as span:
        span.set_attribute("formica.run_id", run_id)
        span.set_attribute("formica.env", env)
        span.set_attribute("formica.region", region)
        span.set_attribute("formica.budget_usd", budget)
        span.set_attribute("formica.timeout_seconds", timeout)
        span.set_attribute("formica.local", local)

        forum = Forum(cfg)
        forum.ensure_schema()
        obj = Objective(
            id=new_id("obj"),
            run_id=run_id,
            text=problem,
            budget_usd=budget,
            timeout_seconds=timeout,
            env=env,
            region=region,
        )
        forum.insert_objective(obj)
        log.info("objective inserted", extra={"run_id": run_id, "objective_id": obj.id,
                                              "trace_id": span.get_span_context().trace_id,
                                              "local": local})

        deadline = time.time() + timeout
        seen: set[str] = set()
        stable: dict[str, int] = {}
        poll = local_tick_seconds if local else 3.0

        # Lazily created on the first tick — keeps K8s-mode fast and avoids
        # importing caste classes when not needed.
        local_tick = _build_local_tick(forum, cfg, obj.id) if local else None

        while time.time() < deadline:
            if local_tick is not None:
                try:
                    local_tick()
                except Exception as e:
                    # A single bad tick must not kill the CLI — log and move on,
                    # mirroring the controller's per-pod isolation.
                    log.exception("local tick failed: %s", e)

            validated = forum.list_validated_evidence(obj.id, cfg.validated_threshold)
            for ev in validated:
                if ev["id"] not in seen:
                    seen.add(ev["id"])
                    stable[ev["id"]] = 1
                    if stream:
                        click.echo(json.dumps({"evidence": ev}, default=str))
                else:
                    stable[ev["id"]] = stable.get(ev["id"], 0) + 1

            ready = [eid for eid, n in stable.items() if n >= cfg.n_stable_cycles]
            if len(ready) >= n_solutions:
                result = {
                    "run_id": run_id,
                    "objective_id": obj.id,
                    "status": "validated",
                    "solutions": [ev for ev in validated if ev["id"] in ready][:n_solutions],
                }
                click.echo(json.dumps(result, default=str, indent=2))
                forum.close()
                return
            time.sleep(poll)

        click.echo(json.dumps({"run_id": run_id, "objective_id": obj.id, "status": "timeout"}))
        forum.close()


def _build_local_tick(forum: "Forum", cfg: "FormicaConfig", objective_id: str):
    """Build a closure that advances the colony by one tick in-process.

    Intended for single-box GPU testing (``formica solve --local``). On each
    tick we:

    1. Scout any Objective or SubProblem that still has no children.
    2. Forage every open SubProblem that has no Evidence yet.
    3. Validate every Evidence that has no Validation yet.
    4. Run one GC pass to evaporate + prune.

    This deliberately does NOT try to model the full capacity-aware controller
    — it's a developer-ergonomics loop for testing on one machine.
    """
    from formica.agents.scout import Scout
    from formica.agents.forager import Forager
    from formica.agents.validator import Validator
    from formica.agents.gc import GarbageCollector
    from formica.agents.base import new_agent_id

    # State across ticks so we don't re-scout the same node forever.
    scouted: set[str] = set()

    def _tick() -> None:
        open_sps = forum.list_open_subproblems(objective_id) or []

        # 1. Scout: expand the root once, then any subproblem we haven't
        #    decomposed yet. Capped per tick to keep latency predictable.
        scout_targets = []
        if objective_id not in scouted:
            scout_targets.append(objective_id)
        scout_targets.extend(sp["id"] for sp in open_sps if sp["id"] not in scouted)
        for focus in scout_targets[:4]:
            Scout(
                agent_id=new_agent_id("scout"),
                caste="scout",
                forum=forum,
                config=cfg,
                focus_id=focus,
            ).tick()
            scouted.add(focus)

        # 2. Forage: one Evidence per open SubProblem that has none yet.
        #    list_open_subproblems returns ev_count; zero means no Evidence.
        for sp in (forum.list_open_subproblems(objective_id) or []):
            if int(sp.get("ev_count") or 0) > 0:
                continue
            Forager(
                agent_id=new_agent_id("forager"),
                caste="forager",
                forum=forum,
                config=cfg,
                focus_id=sp["id"],
            ).tick()

        # 3. Validate any Evidence with no Validation yet.
        for ev in (forum.list_unvalidated_evidence(objective_id) or []):
            Validator(
                agent_id=new_agent_id("validator"),
                caste="validator",
                forum=forum,
                config=cfg,
                focus_id=ev["id"],
            ).tick()

        # 4. One GC tick — evaporation + necrophoresis.
        GarbageCollector(
            agent_id=new_agent_id("gc"),
            caste="gc",
            forum=forum,
            config=cfg,
        ).tick()

    return _tick


@main.command("evaporate")
@click.option("--min-pheromone", type=float, default=1e-4)
def evaporate(min_pheromone: float) -> None:
    """Run a single evaporation pass (used by the CronJob image)."""
    forum = Forum()
    touched = forum.evaporate_all(min_pheromone=min_pheromone)
    click.echo(json.dumps({"evaporated_edges": touched}))
    forum.close()


@main.command("gc")
@click.option("--floor", type=float, default=1e-3)
def gc(floor: float) -> None:
    """Run a single GC pass (necrophoresis)."""
    forum = Forum()
    deleted = forum.prune_dead(pheromone_floor=floor)
    click.echo(json.dumps({"pruned_nodes": deleted}))
    forum.close()


if __name__ == "__main__":
    main()
