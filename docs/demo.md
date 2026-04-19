# Demo: two end-to-end runs

This doc walks through two canonical runs of `formica solve` on a dev
cluster: one math problem (toy, deterministic) and one research problem
(web-tool driven). For each run we show the CLI invocation, the pods that
were spawned, the pheromone fields the colony traversed, and where the
operator can go in CloudWatch and Athena to inspect the evidence trail.

All CloudWatch and S3 names are `{env}`/`{region}` scoped. The examples
use `env=dev`, `region=us-east-1`.

---

## Run 1 — Math: "Prove sqrt(2) is irrational"

### CLI

```bash
formica solve "Prove sqrt(2) is irrational. Present a classical proof." \
  --budget 2 --timeout 600 --env dev --region us-east-1
```

### What happens, tick by tick

1. **`formica solve`** writes an `Objective` node to the Forum (blackboard)
   and deposits `promising=1.0` on the root edge.
2. **Scout** pods read the neighborhood of the root, emit 3–5
   `SubProblem` children ("contradiction approach", "unique factorization
   approach", "continued fractions approach"), and deposit `promising`
   on each.
3. **Controller** ticks every 10s, sees pending subproblems, consults
   `compute_headroom()` against current cluster capacity (it never
   requests new capacity), and spawns Forager pods up to the pool max.
4. **Foragers** sample children with softmax over the `promising`
   pheromone field (τ=0.5), attach `Evidence`, and deposit `validated`
   when their inline sanity checks pass.
5. **Validator** pods read `Evidence` whose parent has `validated>0.5`
   and either confirm (deposit `validated`, push over the 0.7 threshold)
   or reject (deposit `risky`).
6. **Inquiline.numeric** catches any `a=b` equalities and flags
   `risky` if they don't hold.
7. After `N_STABLE_CYCLES=3` ticks with a child edge above
   `VALIDATED_THRESHOLD=0.7`, the coordinator returns that subtree's
   evidence as the answer.
8. **GC** runs `evaporate_all()` on a cron and prunes edges below
   `MIN_PHEROMONE=1e-4`.

### Expected output (abridged)

```
▸ objective: o-3f1a...  pheromone root=promising:1.00
▸ tick 1  pods: scout=1 forager=2 validator=1   headroom: cpu=3.2 mem=7.1Gi
▸ tick 2  deposited promising=0.64 on "contradiction approach"
▸ tick 4  deposited validated=0.82 on "contradiction approach/step-3"
▸ tick 5  stable cycles: 3/3  ← converged
✓ validated answer (subtree o-3f1a.../contradiction approach):
    Assume sqrt(2) = p/q in lowest terms. Then 2q^2 = p^2, so p is even,
    p = 2k, so q^2 = 2k^2, so q is even — contradicting lowest terms. ∎
spend: $0.41 / $2.00   wallclock: 84s / 600s
```

### Where to look

- **Traces (Parquet on S3):** `s3://formica-otel-dev-us-east-1/traces/year=2026/month=04/day=19/`
- **Error logs:** [/formica/dev/us-east-1/errors](https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Fformica$252Fdev$252Fus-east-1$252Ferrors)
- **Driver logs (neo4j, strands, kubernetes, botocore, …):**
  [/formica/dev/us-east-1/drivers](https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Fformica$252Fdev$252Fus-east-1$252Fdrivers)

### Athena query — pheromone history on the winning edge

```sql
SELECT ts, channel, value
FROM formica_otel_dev_us_east_1.pheromone_history
WHERE edge_id = 'e-contradiction-step-3'
  AND year = '2026' AND month = '04' AND day = '19'
ORDER BY ts;
```

Mock result:

| ts                   | channel    | value |
|----------------------|------------|-------|
| 2026-04-19T21:32:10Z | promising  | 0.64  |
| 2026-04-19T21:32:20Z | promising  | 0.61  |
| 2026-04-19T21:32:40Z | validated  | 0.82  |
| 2026-04-19T21:33:00Z | validated  | 0.79  |
| 2026-04-19T21:33:20Z | validated  | 0.77  |

---

## Run 2 — Research: "Compare CNN vs ViT on ImageNet-1k (top-1)"

### CLI

```bash
formica solve "Compare CNN vs ViT top-1 accuracy on ImageNet-1k with sources." \
  --budget 3 --timeout 900 --env dev --region us-east-1
```

### What happens

1. Scout expands the objective into two branches: "CNN families" and
   "ViT families".
2. Foragers call `web_search` / `web_fetch` (tools in
   `formica/tools/web.py`) and attach URL-bearing `Evidence`.
3. **Inquiline.citation** verifies that each cited URL resolves and that
   the claimed numeric figure (e.g. "88.55% top-1") appears in the
   fetched page. Mismatches are pheromone-penalised with `risky`.
4. Validators cross-check figures across sources. Consensus within ±0.3%
   pushes `validated` over threshold.
5. Subtrees that lose to `risky` or `dead-end` decay fast
   (`dead-end` half-life = 120min, `risky` = 10min) and stop attracting
   foragers.

### Expected output (abridged)

```
✓ validated answer:
  CNN (ConvNeXt-XL, IN-21k pretrain): 87.8% top-1 — [paper](https://…)
  ViT  (ViT-H/14, JFT-300M pretrain): 88.55% top-1 — [paper](https://…)
  Gap: ≈0.75 pp in favour of ViT at equivalent pretrain scale.
spend: $1.22 / $3.00  wallclock: 312s / 900s
```

### Where to look

- **Validation outcomes (who rejected what):**

  ```sql
  SELECT validator_pod, subproblem_id, outcome, reason
  FROM formica_otel_dev_us_east_1.validation_outcomes
  WHERE year='2026' AND month='04' AND day='19'
  ORDER BY ts DESC
  LIMIT 50;
  ```

- **Agent lifecycle (spawn/retire events from the Controller):**

  ```sql
  SELECT pod, pool, event, ts, headroom_cpu, headroom_mem
  FROM formica_otel_dev_us_east_1.agent_lifecycle
  WHERE year='2026' AND month='04' AND day='19'
  ORDER BY ts;
  ```

---

## Zero-headroom behaviour

To demonstrate the "never provision" guarantee, cordon every node:

```bash
kubectl get nodes -o name | xargs -I{} kubectl cordon {}
formica solve "…" --budget 1 --timeout 120 --env dev --region us-east-1
```

Expected: the Controller logs `INFO headroom: cpu=0 mem=0, throttling`,
the SNS topic `formica-dev-us-east-1-alerts` fires a `ZeroHeadroom`
alarm, no new pods are created, and no AWS provisioning API is called
(verified by the `ci.yml → No provisioning APIs` grep step and by CloudTrail).

When you uncordon a node, the Controller picks up the new capacity on
its next 10s tick — no restart, no config change.
