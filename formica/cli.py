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
def solve(problem: str, budget: float, timeout: int, env: str, region: str,
          n_solutions: int, stream: bool) -> None:
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
                                              "trace_id": span.get_span_context().trace_id})

        deadline = time.time() + timeout
        seen: set[str] = set()
        stable: dict[str, int] = {}
        poll = 3.0

        while time.time() < deadline:
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
