"""Formica HTTP API.

A thin FastAPI wrapper over the Forum and CLI semantics. Exposes enough
surface area to submit objectives and inspect the colony state without
needing kubectl exec.

Endpoints:
  POST /v1/objectives            - submit a problem, returns {objective_id, run_id}
  GET  /v1/objectives/{id}       - status + validated evidence for this objective
  GET  /v1/objectives/{id}/graph - full neighborhood (nodes + edges + pheromones)
  GET  /v1/healthz               - neo4j reachability

This module is intentionally small. All domain logic stays on the Forum
class. The API is just a transport. If you need to extend it, prefer
adding a method to Forum and a 5-line route here.

Run directly:
    uvicorn formica.api:app --host 0.0.0.0 --port 8000
In-cluster it runs as the `formica-api` Deployment (see deploy/k8s/base/api.yaml).
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from formica.blackboard.forum import Forum, new_id
from formica.blackboard.models import Objective
from formica.config import FormicaConfig

app = FastAPI(title="Formica API", version="0.1.0")

_config = FormicaConfig()
_forum = Forum(_config)


class SubmitObjectiveRequest(BaseModel):
    problem: str = Field(..., min_length=1)
    budget_usd: float = 1.0
    timeout_seconds: int = 600
    env: str = "dev"
    region: str = "us-east-1"


class SubmitObjectiveResponse(BaseModel):
    objective_id: str
    run_id: str


@app.on_event("startup")
def _startup() -> None:
    _forum.ensure_schema()


@app.on_event("shutdown")
def _shutdown() -> None:
    _forum.close()


@app.get("/v1/healthz")
def healthz() -> dict:
    """Neo4j reachability check. Returns 200 even if LLM is down; the API
    does not depend on vLLM to serve reads, only the agents do."""
    try:
        with _forum._session() as s:
            s.run("RETURN 1").single()
        return {"status": "ok", "neo4j": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"neo4j unreachable: {e}")


@app.post("/v1/objectives", response_model=SubmitObjectiveResponse)
def submit_objective(req: SubmitObjectiveRequest) -> SubmitObjectiveResponse:
    """Write an Objective to the Forum. The in-cluster controller will pick
    it up on its next tick and spawn Scouts against it. Clients poll the
    objective endpoint (or stream validated evidence out of Neo4j directly)
    to watch progress."""
    run_id = uuid.uuid4().hex
    obj = Objective(
        id=new_id("obj"),
        run_id=run_id,
        text=req.problem,
        budget_usd=req.budget_usd,
        timeout_seconds=req.timeout_seconds,
        env=req.env,
        region=req.region,
    )
    _forum.insert_objective(obj)
    return SubmitObjectiveResponse(objective_id=obj.id, run_id=run_id)


@app.get("/v1/objectives/{objective_id}")
def get_objective(objective_id: str) -> dict:
    """Return the objective's current validated Evidence plus counts.
    Mirrors the CLI poll loop but as a single snapshot."""
    with _forum._session() as s:
        obj_rec = s.run(
            "MATCH (o:Objective {id: $id}) RETURN o",
            id=objective_id,
        ).single()
        if obj_rec is None:
            raise HTTPException(status_code=404, detail="objective not found")
        sub_count = s.run(
            "MATCH (o:Objective {id: $id})<-[:CHILD_OF*1..6]-(sp:SubProblem) "
            "RETURN count(sp) AS n",
            id=objective_id,
        ).single()["n"]
        evidence_count = s.run(
            "MATCH (o:Objective {id: $id})<-[:CHILD_OF*1..6]-(:SubProblem)"
            "<-[:SUPPORTS]-(e:Evidence) RETURN count(e) AS n",
            id=objective_id,
        ).single()["n"]
    validated = _forum.list_validated_evidence(objective_id, _config.validated_threshold)
    return {
        "objective_id": objective_id,
        "objective": dict(obj_rec["o"]),
        "subproblem_count": sub_count,
        "evidence_count": evidence_count,
        "validated_count": len(validated),
        "validated": validated,
    }


@app.get("/v1/objectives/{objective_id}/graph")
def get_objective_graph(objective_id: str, radius: int = 6) -> dict:
    """Full subgraph for an Objective: nodes + edges + pheromone channel
    values. This is the payload you want for studying colony behavior."""
    nb = _forum.read_neighborhood(objective_id, radius=max(1, min(radius, 8)))
    if nb["focus"] is None:
        raise HTTPException(status_code=404, detail="objective not found")
    return nb
