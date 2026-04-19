# ADR-0001: Stigmergy over hierarchy

**Status**: Accepted
**Date**: 2026-04-19

## Context

Rome coordinates agents through a hierarchy: Princeps → Legate/Magistrate → Legionary/Artisan,
with a Censor aggregating metrics. This model scales badly once the problem graph becomes
wide: the manager becomes a bottleneck, and every decision requires a round-trip through it.

## Decision

Formica replaces all dispatcher/manager components with a shared, pheromone-weighted
blackboard (the Forum, implemented as Neo4j). Workers read a local neighborhood, sample
an action by pheromone gradient, and write pheromone back. No inter-agent chat channels exist.

## Consequences

- **+** No single point of coordination. The colony throughput scales with worker count and
  Neo4j write throughput, not with a manager's LLM latency.
- **+** Emergent specialization via Gordon's rule — no need to pre-classify work as
  "legion" or "civitas".
- **+** Failure is local. A dead worker leaves stale pheromone that evaporates; no
  orphan-reconciliation logic needed.
- **−** Requires careful pheromone tuning (half-lives, thresholds). Captured in
  `docs/pheromones.md`.
- **−** Harder to debug by reading logs linearly. Mitigated by OTEL spans per tick
  and the Athena query pack.
