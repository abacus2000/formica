# Formica — Follow-ups

Things deferred during the MVP slim-down (April 2026). Pick up any of
these when you come back. None are blockers for using the system.

## Known bugs

### Validator pool not promoting Evidence

During the April 21 smoke run (`obj-c1a63f3657e3`, problem: "prove that
sqrt(2) is irrational"), the colony produced 46 SubProblems and 13
Evidence nodes within ~90 seconds, but `validated_count` stayed at 0.

Suspected causes (in order of likelihood):

1. Validator confidence threshold too high for short runs.
2. Validator pool not getting scheduled at all — check
   `kubectl -n formica get pods -l formica.pool=validator`.
3. `VALIDATE` edges written but `validated=true` flag never flipped on
   Evidence node.

Debug path:

```bash
sudo kubectl -n formica logs -l formica.pool=validator --tail=200
sudo kubectl -n formica exec neo4j-0 -- cypher-shell -u neo4j -p changeme \
  'MATCH (e:Evidence)-[r:VALIDATES]->(s) RETURN e.id, r.confidence, s.id LIMIT 20'
```

### Stale observability pods still running

`kubectl apply -k` does not delete resources removed from a manifest, so
`otel-collector` and `aws-for-fluent-bit` are still running even though
they are commented out of `deploy/k8s/base/kustomization.yaml`. Cosmetic.
Clean up manually with:

```bash
sudo kubectl -n formica delete deploy otel-collector --ignore-not-found
sudo kubectl -n formica delete ds aws-for-fluent-bit --ignore-not-found
```

## Features gated off in MVP

All flags live in `formica/config.py`, all default `"off"`. Flip to
`"on"` via the `formica-controller` Deployment env to re-enable. Each
was cut purely for credit preservation; all code paths are still in the
tree.

| Flag                          | What it gates                                     | Where wired |
| ----------------------------- | ------------------------------------------------- | ----------- |
| `FORMICA_OBSERVABILITY`       | OTEL exporter in `formica/telemetry/otel.py`      | wired       |
| `FORMICA_PHASES`              | Entropy-driven phase cycling in controller        | wired       |
| `FORMICA_INQUILINES`          | Narrow specialist castes (citation / numeric)     | declared, not wired |
| `FORMICA_ALARM_PREEMPT_ENABLED` | Short-lived alarm pheromone preemption          | declared, not wired |

To restore the full observability stack, uncomment these two lines in
`deploy/k8s/base/kustomization.yaml`:

```yaml
# - ../../otel-collector
# - ../../fluent-bit
```

and set `FORMICA_OBSERVABILITY=on` on the controller Deployment.

## Architectural follow-ups

### API surface expansion

Today's 4 endpoints are the minimum. When you want real UX:

- `GET /v1/objectives` — list recent objectives (currently must know id).
- `DELETE /v1/objectives/{id}` — cancel run, delete subtree.
- `GET /v1/objectives/{id}/stream` — SSE for live SubProblem / Evidence
  events (the CLI streaming path already exists; just expose it over
  HTTP).
- `GET /v1/pods` — pivot view of caste mix (thin wrapper over
  `kubectl get pods -l formica.pool`).
- Auth: currently no auth. Fine for laptop port-forward, not fine for
  anything internet-facing. Add an API key header check in
  `formica/api.py` before first public deploy.

### Graph response shape

`GET /v1/objectives/{id}/graph` returns `{focus, neighbors, edges}`
where `neighbors` mixes SubProblems and Evidence with a `_labels` array.
Consider splitting into explicit `subproblems` and `evidence` fields so
clients do not have to filter by label string.

### vLLM Deployment label bug (root cause post-mortem)

On April 21 the `vllm` Service had selector
`{component: vllm, instance: formica}` (added by kustomize `labels`
block with `includeSelectors: true`), but the live pod only carried
`component: vllm` — so endpoints was empty and every scout saw
`APIConnectionError`. Fix was to delete the Deployment and reapply, so
kustomize could rebuild the pod template.

The underlying issue is that Deployment `.spec.selector` is immutable
once set: if someone adds a new common label later, `kubectl apply` will
silently refuse to update the selector, leaving pods mislabeled.

Mitigation options (pick one before next kustomize label change):

1. Always delete + recreate Deployments when adding common labels.
2. Stop using kustomize `labels` with `includeSelectors: true` — bake
   the full selector into each manifest by hand.
3. Switch to Helm, which handles this correctly.

## Re-enabling Docker path

Docker was purged from the deployment path but is still baked into the
AMI. If you want to re-add a Docker Compose stack alongside k3s, the
last working compose file is recoverable from git history
(`git log --all --oneline -- docker-compose.yml`). Recommend not doing
this — k3s single-box is the first-class path.

## Credit-friendly test workflow

Cold-start vLLM costs ~90s of GPU time (CUDA graph compile + weights
load). Keep it running once you start studying. When done for the day:

```bash
aws ec2 stop-instances --instance-ids i-XXXXXXXXXXXXXXXXX --region us-east-1
```

Restart is cheap (~2 min for all pods to come back, since k3s + weights
live on the root volume).

## Key session artifacts (April 21, 2026)

- PR #26 (merged): added FastAPI service + feature flag gates.
  https://github.com/abacus2000/formica/pull/26
- Test objective: `obj-c1a63f3657e3` — produced 46 SubProblems, 13
  Evidence, 0 validated.
- Working instance: `i-03314039e456d8f74` in `us-east-1`.
- Model: `Qwen/Qwen2.5-7B-Instruct-AWQ` on a g5.xlarge (A10G).
