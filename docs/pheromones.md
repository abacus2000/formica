# Pheromones

Pheromones are scalar, time-decaying weights on graph edges. Each edge carries a list of
`(channel, value, updated_at, half_life_s)` entries.

## Channels

| Channel         | Meaning                                              | Default half-life | Evaporation cadence |
| --------------- | ---------------------------------------------------- | -----------------: | -------------------- |
| `promising`     | A Forager thinks this edge is worth walking.         | 15 minutes         | every 60s            |
| `validated`     | A Validator has confirmed the linked Evidence.       | 60 minutes         | every 60s            |
| `risky`         | An Inquiline flagged the edge as suspicious.         | 10 minutes         | every 60s            |
| `needs-expert`  | Requires a specialist Inquiline (citation, numeric). | 20 minutes         | every 60s            |
| `dead-end`      | A Validator refuted this Evidence.                   | 120 minutes        | every 60s            |
| `alarm`         | Hallucination, tool failure, or budget overrun.      | 30 seconds         | every 10s            |

## Evaporation math

Exponential decay:

```
value(t) = value_0 * 0.5 ** ((t - updated_at) / half_life_s)
```

A CronJob runs the evaporation pass on the cadence above; pheromones under
`MIN_PHEROMONE` (default `1e-4`) are removed.

## Deposition

Agents deposit pheromone by Cypher UPSERT on an edge. If the same `(edge, channel)` already
has a value, the new deposit is **additive** up to a ceiling of `1.0`:

```cypher
MATCH (a)-[r]->(b) WHERE id(r) = $edge_id
WITH r, [p IN coalesce(r.pheromones, []) WHERE p.channel <> $channel] AS others,
     [p IN coalesce(r.pheromones, []) WHERE p.channel = $channel] AS same
WITH r, others, coalesce(head(same).value, 0.0) AS prev
SET r.pheromones = others + [{
  channel: $channel, value: apoc.coll.min([1.0, prev + $amount]),
  updated_at: timestamp() / 1000, half_life_s: $half_life
}]
```

## Gradient sampling

A Forager at node `u` samples the next edge by weighted softmax over neighbor
`promising` pheromone (with `dead-end` subtracted and `alarm` forcing an early exit):

```
w_e = max(0, promising(e) - beta*dead_end(e))
p_e = softmax(w_e / tau)
```

With an `alarm` pheromone anywhere in the local neighborhood above `ALARM_PREEMPT`, the
agent aborts its current plan and emits a `risky` deposit on the incoming edge.

## Tuning

All thresholds live in `formica/pheromones/constants.py` and can be overridden via
Helm values (`pheromones.*`) without rebuilding images.
