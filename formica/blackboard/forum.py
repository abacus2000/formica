"""The Forum — Neo4j-backed blackboard DAL.

Every agent interaction goes through this class. It is the only place in the
codebase that should talk to Neo4j directly.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager

from formica.blackboard.cypher import DEPOSIT_PHEROMONE, SCHEMA_CYPHER
from formica.blackboard.models import Alarm, Evidence, Objective, SubProblem, Validation
from formica.config import FormicaConfig
from formica.pheromones.constants import DEFAULT_HALF_LIFE
from formica.pheromones.decay import evaporate

logger = logging.getLogger(__name__)


class Forum:
    """Neo4j-backed blackboard. Thread-safe per driver, stateless per call."""

    def __init__(self, config: FormicaConfig | None = None):
        self.config = config or FormicaConfig()
        self._driver = None

    def connect(self):
        from neo4j import GraphDatabase

        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.config.neo4j_uri,
                auth=(self.config.neo4j_user, self.config.neo4j_password),
            )
        return self._driver

    def close(self):
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    @contextmanager
    def _session(self):
        drv = self.connect()
        with drv.session(database=self.config.neo4j_database) as s:
            yield s

    # ---------- schema ----------

    def ensure_schema(self) -> None:
        with self._session() as s:
            for stmt in SCHEMA_CYPHER:
                s.run(stmt)

    # ---------- node writes ----------

    def insert_objective(self, obj: Objective) -> str:
        with self._session() as s:
            s.run(
                "MERGE (o:Objective {id: $id}) SET o += $props",
                id=obj.id,
                props=obj.model_dump(),
            )
        return obj.id

    def insert_subproblem(self, sp: SubProblem) -> str:
        cypher = """
        MATCH (parent) WHERE parent.id = $parent_id
        MERGE (c:SubProblem {id: $id}) SET c += $props
        MERGE (c)-[r:CHILD_OF]->(parent)
        ON CREATE SET r.pheromones = []
        RETURN elementId(r) AS edge_id
        """
        with self._session() as s:
            rec = s.run(cypher, id=sp.id, parent_id=sp.parent_id, props=sp.model_dump()).single()
            return rec["edge_id"] if rec else ""

    def insert_evidence(self, ev: Evidence) -> str:
        cypher = """
        MATCH (sp:SubProblem {id: $sp_id})
        MERGE (e:Evidence {id: $id}) SET e += $props
        MERGE (e)-[r:SUPPORTS]->(sp)
        ON CREATE SET r.pheromones = []
        RETURN elementId(r) AS edge_id
        """
        with self._session() as s:
            rec = s.run(cypher, id=ev.id, sp_id=ev.subproblem_id, props=ev.model_dump()).single()
            return rec["edge_id"] if rec else ""

    def insert_validation(self, v: Validation) -> str:
        cypher = """
        MATCH (e:Evidence {id: $ev_id})
        MERGE (val:Validation {id: $id}) SET val += $props
        MERGE (val)-[r:VERDICTS]->(e)
        ON CREATE SET r.pheromones = []
        RETURN elementId(r) AS edge_id
        """
        with self._session() as s:
            rec = s.run(cypher, id=v.id, ev_id=v.evidence_id, props=v.model_dump()).single()
            return rec["edge_id"] if rec else ""

    def insert_alarm(self, a: Alarm) -> str:
        cypher = """
        MERGE (al:Alarm {id: $id}) SET al += $props
        WITH al
        OPTIONAL MATCH (t) WHERE t.id = $target_id
        FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
          MERGE (al)-[:ALARMS]->(t)
        )
        """
        with self._session() as s:
            s.run(cypher, id=a.id, target_id=a.target_id, props=a.model_dump())
        return a.id

    # ---------- pheromone writes ----------

    def deposit(
        self,
        edge_id: str,
        channel: str,
        amount: float,
        half_life_s: int | None = None,
    ) -> None:
        half = half_life_s or DEFAULT_HALF_LIFE.get(channel, 600)
        with self._session() as s:
            s.run(
                DEPOSIT_PHEROMONE,
                edge_id=edge_id,
                channel=channel,
                amount=float(amount),
                now=time.time(),
                half_life_s=float(half),
            )

    # ---------- reads ----------

    def read_neighborhood(self, focus_id: str, radius: int = 2) -> dict:
        """Return nodes and edges within `radius` hops of the focus node."""
        cypher = (
            "MATCH (focus {id: $focus_id}) "
            "OPTIONAL MATCH p = (focus)-[*1.." + str(int(radius)) + "]-(neighbor) "
            "WITH focus, collect(DISTINCT neighbor) AS nbrs, "
            "     collect(DISTINCT relationships(p)) AS rels "
            "RETURN focus, nbrs, rels"
        )
        with self._session() as s:
            rec = s.run(cypher, focus_id=focus_id).single()
            if rec is None:
                return {"focus": None, "neighbors": [], "edges": []}
            focus = dict(rec["focus"]) if rec["focus"] else None
            neighbors = [dict(n) for n in rec["nbrs"] if n is not None]
            # Flatten paths → distinct edge dicts keyed by elementId
            seen: dict[str, dict] = {}
            for path_rels in rec["rels"] or []:
                for r in path_rels:
                    eid = r.element_id
                    if eid not in seen:
                        seen[eid] = {
                            "id": eid,
                            "type": r.type,
                            "start": r.start_node["id"] if "id" in r.start_node else None,
                            "end": r.end_node["id"] if "id" in r.end_node else None,
                            "pheromones": list(r.get("pheromones") or []),
                        }
            return {"focus": focus, "neighbors": neighbors, "edges": list(seen.values())}

    def list_open_subproblems(self, objective_id: str, limit: int = 32) -> list[dict]:
        cypher = """
        MATCH (o:Objective {id: $oid})<-[:CHILD_OF*1..6]-(sp:SubProblem)
        OPTIONAL MATCH (sp)<-[r:SUPPORTS]-(:Evidence)
        WITH sp, count(r) AS ev_count
        RETURN sp.id AS id, sp.text AS text, ev_count
        ORDER BY ev_count ASC
        LIMIT $limit
        """
        with self._session() as s:
            return [dict(r) for r in s.run(cypher, oid=objective_id, limit=limit)]

    def list_validated_evidence(
        self, objective_id: str, threshold: float
    ) -> list[dict]:
        cypher = """
        MATCH (o:Objective {id: $oid})<-[:CHILD_OF*1..6]-(sp:SubProblem)<-[r:SUPPORTS]-(e:Evidence)
        WITH e, r, sp,
             [p IN coalesce(r.pheromones, []) WHERE p.channel = 'validated' | p.value] AS vs
        WHERE size(vs) > 0 AND head(vs) >= $threshold
        RETURN e.id AS id, e.content AS content, sp.id AS sp_id,
               head(vs) AS validated, e.sources AS sources
        """
        with self._session() as s:
            return [dict(r) for r in s.run(cypher, oid=objective_id, threshold=threshold)]

    # ---------- evaporation ----------

    def evaporate_all(self, min_pheromone: float = 1e-4) -> int:
        """Recompute every edge's pheromone list. Returns edge count touched."""
        with self._session() as s:
            rows = list(s.run("MATCH ()-[r]->() WHERE r.pheromones IS NOT NULL "
                              "RETURN elementId(r) AS eid, r.pheromones AS pher"))
            touched = 0
            for row in rows:
                new = evaporate(row["pher"], min_pheromone=min_pheromone)
                s.run(
                    "MATCH ()-[r]->() WHERE elementId(r) = $eid SET r.pheromones = $pher",
                    eid=row["eid"],
                    pher=new,
                )
                touched += 1
            return touched

    # ---------- GC (necrophoresis) ----------

    def prune_dead(self, pheromone_floor: float = 1e-3) -> int:
        """Delete orphan Evidence/SubProblem nodes whose all-channel pheromone is under floor."""
        cypher = """
        MATCH (n)
        WHERE (n:Evidence OR n:SubProblem)
          AND NOT (n)-[:CHILD_OF]->(:Objective)
        OPTIONAL MATCH (n)-[r]-()
        WITH n,
             reduce(s = 0.0, p IN [x IN coalesce(collect(r.pheromones), []) | x] | s) AS _ignored,
             [x IN coalesce(collect(r), []) | coalesce(x.pheromones, [])] AS all_pher_lists
        WITH n,
             reduce(total = 0.0, lst IN all_pher_lists |
               total + reduce(s = 0.0, p IN lst | s + coalesce(p.value, 0.0))
             ) AS mass
        WHERE mass < $floor
        DETACH DELETE n
        RETURN count(n) AS deleted
        """
        with self._session() as s:
            rec = s.run(cypher, floor=pheromone_floor).single()
            return int(rec["deleted"]) if rec else 0


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
