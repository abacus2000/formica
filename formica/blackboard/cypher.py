"""Cypher schema and reusable query fragments."""

from __future__ import annotations

SCHEMA_CYPHER = [
    "CREATE CONSTRAINT objective_id IF NOT EXISTS FOR (n:Objective) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT subproblem_id IF NOT EXISTS FOR (n:SubProblem) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT validation_id IF NOT EXISTS FOR (n:Validation) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT alarm_id IF NOT EXISTS FOR (n:Alarm) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX evidence_sub IF NOT EXISTS FOR (n:Evidence) ON (n.subproblem_id)",
    "CREATE INDEX validation_ev IF NOT EXISTS FOR (n:Validation) ON (n.evidence_id)",
]


DEPOSIT_PHEROMONE = """
MATCH ()-[r]->() WHERE elementId(r) = $edge_id
WITH r, coalesce(r.pheromones, []) AS pher
WITH r,
     [p IN pher WHERE p.channel <> $channel] AS others,
     [p IN pher WHERE p.channel = $channel] AS same
WITH r, others,
     coalesce(head([p IN same | p.value]), 0.0) AS prev
SET r.pheromones = others + [{
  channel: $channel,
  value: CASE WHEN prev + $amount > 1.0 THEN 1.0 ELSE prev + $amount END,
  updated_at: toFloat($now),
  half_life_s: toFloat($half_life_s)
}]
RETURN elementId(r) AS edge_id
"""


READ_LOCAL_NEIGHBORHOOD = """
MATCH (focus) WHERE focus.id = $focus_id
OPTIONAL MATCH path = (focus)-[*1..$radius]-(neighbor)
WITH focus, collect(DISTINCT neighbor) AS neighbors, collect(DISTINCT relationships(path)) AS rels
RETURN focus, neighbors, rels
"""
