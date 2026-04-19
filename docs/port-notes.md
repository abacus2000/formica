# Port notes: `rome` → `formica`

This document maps every `rome` concept to its `formica` equivalent and records what is
**kept**, **changed**, or **dropped**. Where a concept is changed, the rationale is given
and, for stack-level changes, an ADR is added under `docs/decisions/`.

## Architectural thesis

Rome is **hierarchical**: a Princeps decides, a Legate/Magistrate manages, and Legionaries/Artisans
execute. Communication is request/response over HTTP plus JSONL files on a PVC.

Formica is **stigmergic**: there is no dispatcher. All agents share a Neo4j blackboard ("Forum")
whose edges carry pheromone scalars on multiple channels. Each agent reads a local neighborhood,
samples its next action by pheromone gradient, and writes pheromone back. Coordination is emergent.

## Concept map

| Rome concept                      | Formica equivalent                                    | Keep/Change/Drop | Notes |
| --------------------------------- | ----------------------------------------------------- | ---------------- | ----- |
| Princeps (decides legion/civitas) | *(removed)*                                           | Drop             | No top-down deployment choice; the colony converges via pheromones. CLI submits objective directly to the Forum. |
| Legion vs. Civitas split          | Single worker pool with role reallocation             | Change           | Gordon's rule (encounter-rate reallocation) replaces up-front mode selection. |
| Legate / Magistrate (managers)    | Spawn/retire controller (one, cluster-wide)           | Change           | Controller is capacity-aware (see `docs/capacity.md`); manages pool budgets, not per-initiative squads. |
| Legionary / Artisan (workers)     | **Forager** caste                                     | Change           | Stateless tick-loop workers; no per-initiative squad ownership. |
| *(new)*                           | **Scout** caste                                       | Add              | Creates new sub-problem nodes; decays rapidly unless picked up. |
| Censor (metrics sink)             | **Validator** caste + OTEL to S3 (traces/metrics)     | Change           | Validators are first-class agents that emit `validated` / `dead-end` pheromone. Raw metrics go to OTEL, not a HTTP sink. |
| Scholar (cross-ref)               | **Inquiline: citation-checker**                       | Change           | Narrow agent that activates only when `needs-expert` pheromone appears on a citation node. |
| Augur (experimental proposals)    | Scout caste with low-evaporation `promising` seeding  | Change           | Exploration is a phase of the colony, not a separate role. |
| Senate / Tribune / Optio (kaizen) | Phase cycling + `anternet` spawn feedback             | Change           | Meta-optimization is automatic, driven by pheromone entropy and validated-per-compute-second yield. |
| HTTP-based inter-service messaging | *(removed)*                                          | Drop             | All state lives in the Forum. Pods read/write Neo4j. |
| Censor JSONL storage              | *(removed)*                                           | Drop             | Replaced by OTEL → S3 Parquet and CloudWatch logs. |
| `rome-manager` ServiceAccount     | `formica-controller` + `formica-agent` SAs            | Change           | Finer-grained RBAC; agents don't need Job creation rights. |
| InitiativeSpec (Pydantic)         | `Objective` node in Neo4j                             | Change           | First-class graph node, not a transient Pydantic object. |
| TaskAssignment                    | `SubProblem` node                                     | Change           | Created by Scouts; claimed by Foragers via pheromone gradient. |
| FindingReport                     | `Evidence` node + `Validation` node                   | Change           | Evidence is written; a Validator emits a Validation node with a verdict and a `validated` pheromone weight. |
| CensorEntry                       | *(removed)*                                           | Drop             | OTEL spans carry equivalent information. |
| KaizenReport / ScalingDecision    | `PhaseTransition` graph events                        | Change           | Recorded as events; no human-readable reports needed for the control loop. |
| `RomeK8sClient.create_worker_job` | `CapacityAwareSpawner.spawn()`                        | Change           | Checks headroom before creating; respects per-pool budget. |
| DuckDuckGo `web_search` / `web_fetch` | Same tools, carried over                          | Keep             | Moved to `formica/tools/web.py`. |
| ATT&CK MCP server                 | *(pack-able, not included)*                           | Drop (for v0.1)  | Can be added as a pack later; not required for acceptance. |
| AWS MCP tool for exec on GPU box  | `formica/tools/aws_exec.py`                           | Keep             | Executes commands on **existing** GPU instances only. No provisioning paths. |
| *(new)*                           | **GC (Lustrum) caste**                                | Add              | Necrophoresis - prunes nodes whose all-channel pheromone is below threshold. |
| *(new)*                           | **Alarm pheromone**                                   | Add              | Fast decay, wide radius; preempts work on hallucination/tool failure/budget overrun. |

## Stack decisions

### Kept
- **Kubernetes** (EKS) as runtime. Minikube supported for local dev.
- **Strands Agents** as the LLM agent primitive.
- **Neo4j** as the graph store - promoted from an ATT&CK-pack optional to the core Forum.
- **AWS MCP tool** for executing commands on pre-existing GPU instances.
- **Helm** (and Kustomize overlays) for deployment.

### Added
- **OpenTelemetry Collector** (OTLP in, S3 Parquet out) - see ADR-0002.
- **aws-for-fluent-bit** DaemonSet - see ADR-0003.
- **Terraform** for cloud resources (S3, Glue, CloudWatch log groups, SNS, IAM) scoped by `{env}`/`{region}` - see ADR-0004.
- **Click-based CLI** `formica solve ...` - see ADR-0005.

### Dropped
- **Princeps service / Senate / Augur / Optio / Tribune** - replaced by emergent coordination (ADR-0001).
- **Censor HTTP service + PVC** - replaced by OTEL + S3 (ADR-0002).
- **Any GPU-capacity provisioning MCP** - explicitly excluded by constraint. Capacity is
  observed, never requested (ADR-0006).

## Read order for maintainers

1. `docs/architecture.md`
2. `docs/pheromones.md`
3. `docs/capacity.md`
4. `docs/observability.md`
5. ADRs under `docs/decisions/`

## Deviations log

All stack-level deviations from `rome` have a matching ADR. If you add another deviation
(e.g., swap Neo4j for TigerGraph, swap Strands for LangGraph), add a new ADR and link it here.
