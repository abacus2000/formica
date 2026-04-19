# References

This is the academic reading list behind Formica's design. Each entry
says what the paper contributes, what else in the ecosystem draws on
the same idea, and which specific Formica components or sections of
this codebase the paper inspired.

The list is intentionally narrow: peer-reviewed journal articles,
arXiv preprints, and primary-source institutional reporting. Blog
posts, forum threads, and encyclopedia entries are useful for
intuition but are not cited as sources of record.

## Reading order

Shortest path through the material:

1. Rodriguez 2026 (Pressure Fields)
2. Garg, Shiragur, Gordon, Charikar 2023 (arboreal ants shortest path)
3. Chandrasekhar, Gordon, Navlakha 2018 (arboreal ants trail repair)
4. Prabhakar, Dektar, Gordon 2012 (Anternet, via the Stanford
   Engineering report)
5. Gordon & Mehdiabadi 1999 (encounter rate task allocation)
6. Friedman, Tschantz, Ramstead, Friston, Constant 2021 (Active
   Inferants)

That sequence walks from system architecture to distributed control
to the colony-level biology that makes the metaphor hold up.

## Architecture

### Emergent Coordination in Multi-Agent Systems via Pressure Fields and Temporal Decay

- Rodriguez, R. (2026). arXiv:2601.08129.
  [link](https://arxiv.org/abs/2601.08129)
- **What it contributes.** A formal argument and empirical benchmark
  for coordinating LLM agents through gradients on a shared artifact
  rather than through explicit orchestration. Proves convergence
  under mild conditions and shows 48.5% solve rate on meeting room
  scheduling vs 12.6% for conversation-based, 1.5% for hierarchical,
  0.4% for sequential baselines across 1,350 trials. Ablation
  demonstrates temporal decay is essential: disabling it drops solve
  rate by 10 percentage points.
- **Seen elsewhere.** The "shared artifact + decay" formulation is
  the LLM-era restatement of the 1980s blackboard architecture
  (Hayes-Roth 1985, below) with time-varying weights instead of a
  static scheduler. Pressure-field thinking also appears in robot
  swarm coordination and in the ant-colony optimization family
  descended from Dorigo's 1992 thesis.
- **Inspires in Formica.**
  - The six pheromone channels with per-channel evaporation
    half-lives (`formica/pheromones/constants.py`) are a direct
    implementation of "pressure gradients with temporal decay."
  - The controller's decision to never provision new compute
    (ADR-0006) follows the paper's observation that coordination
    overhead, not raw capacity, is the limiting factor.
  - The `validated` pheromone as first-class signal (vs logs) is the
    "measurable quality signal" from the paper's Section on quality
    gradients.

### Self-Organizing Multi-Agent Systems for Continuous Software Development

- Lyu, W., Xiao, Y., Zhang, Y., Sun, Y. (2026). arXiv:2603.25928.
  [link](https://arxiv.org/abs/2603.25928)
- **What it contributes.** Three-phase state machine (Strategy to
  Execution to Verification), self-organizing teams where manager
  agents hire / assign / fire workers based on project state, and
  asynchronous human oversight for milestone-driven work. Tests on
  real software projects over multiple days.
- **Seen elsewhere.** The hire/fire-by-need pattern echoes dynamic
  thread-pool sizing in server runtimes and the autoscaler pattern
  in Kubernetes. The explicit Verification phase is the modern form
  of the classic test-in-loop idea from extreme programming.
- **Inspires in Formica.**
  - Phase cycling in `formica/coordinator/phases.py` (exploration
    vs consolidation) borrows the idea of globally-visible phase
    state that gates which agents act when, though Formica swaps
    Strategy/Execution/Verification for exploration/consolidation
    driven by pheromone entropy.
  - The Validator caste mirrors their Verification phase: a
    dedicated caste that only judges, never produces.
  - The capacity controller's spawn/retire loop is the "hire and
    fire" primitive, constrained by ADR-0006 to never ask for more
    compute than the cluster already has.

### BB1: An architecture for blackboard systems that control, explain, and learn about their own behavior

- Hayes-Roth, B. (1984). Stanford Heuristic Programming Project
  Report No. 84-16; see also Hayes-Roth (1985), *Artificial
  Intelligence* 26(3), 251-321.
  [link](http://i.stanford.edu/pub/cstr/reports/cs/tr/84/1034/CS-TR-84-1034.pdf)
- **What it contributes.** The canonical blackboard-architecture
  paper. Defines a domain blackboard, a separate control blackboard,
  independent knowledge sources that read and write the blackboards,
  and a scheduler that uses control heuristics recorded on the
  control blackboard to pick the next action. Forty-plus years on,
  it is still the cleanest framing of "no direct messaging between
  agents, only writes to a shared artifact."
- **Seen elsewhere.** HEARSAY-II speech understanding, classical
  expert systems, most modern workflow engines that use a shared
  state store instead of message queues. The "event store + handlers"
  pattern in distributed systems is a lineal descendant.
- **Inspires in Formica.**
  - The Forum (Neo4j graph) is the domain blackboard. There is
    deliberately no second control blackboard - Formica folds
    control into pheromone gradients on the same graph, which
    Rodriguez 2026 argues is sufficient and lower-overhead.
  - Castes map to knowledge sources: each caste reads a
    well-defined slice of the graph and writes a well-defined set
    of node or edge types. No caste reads another caste's
    scratchpad.

## Distributed algorithms inspired by ants

### Distributed algorithms from arboreal ants for the shortest path problem

- Garg, S., Shiragur, K., Gordon, D. M., Charikar, M. (2023). *PNAS*
  120(6), e2207959120.
  [link](https://www.pnas.org/doi/10.1073/pnas.2207959120) ·
  [code](https://github.com/shivamg13/Arboreal-Ants)
- **What it contributes.** A biologically plausible reinforced
  random walk that converges to the minimum-leakage path under
  constant flow and to the shortest path under increasing flow, with
  a linear decision rule. The convergence proofs require
  bidirectional flow and proportional-to-pheromone edge selection;
  nonlinear decision rules still improve on baselines in >80% of
  simulations but lose formal guarantees. Strictly distinct from
  ant-colony optimization (ACO): no individual memory, no
  retracing.
- **Seen elsewhere.** The linear-rule + bidirectional-flow
  combination shows up in network routing under the name "valiant
  load balancing" and in some consensus protocols where probabilistic
  preference for higher-weighted edges yields convergence without a
  coordinator.
- **Inspires in Formica.**
  - The pheromone update step in the Forum - "add on traversal,
    multiply by decay each tick" - is the paper's equation 3
    applied to task-graph edges instead of physical vine edges.
  - The `promising` and `validated` pheromone channels implement
    bidirectional flow: foragers lay `promising` going in, validators
    lay `validated` coming out. The combination is what the paper
    shows is necessary for convergence.
  - The phase-cycling rule "increase activity when entropy drops"
    is inspired by the paper's result that *increasing* flow rate
    converts minimum-leakage convergence into shortest-path
    convergence.

### A distributed algorithm to maintain and repair the trail networks of arboreal ants

- Chandrasekhar, A., Gordon, D. M., Navlakha, S. (2018). *Scientific
  Reports* 8, 9297.
  [link](https://www.nature.com/articles/s41598-018-27160-3)
- **What it contributes.** The RankEdge random walk: rank outgoing
  edges by pheromone weight, pick within rank-ties uniformly, use
  explore probability `q_explore ^ i` for the i-th rank. Field-fit
  parameters: `q_decay = 0.02`, `q_explore = 0.20`. Four design
  choices the paper proves are necessary for good repair behavior:
  (1) bidirectional concurrent search from both sides of a break,
  (2) no backtracking to immediate previous node, (3) no pheromone
  on return from dead ends, (4) one-ant-per-node-per-timestep
  queueing. Achieves 70% repair success on Full grid topologies.
- **Seen elsewhere.** Self-healing overlay networks (Chord, Kademlia
  after churn), gossip protocols with anti-entropy repair, BGP
  convergence after link failures. The "no pheromone on dead-end
  return" trick is the same insight as negative acknowledgment in
  transport protocols.
- **Inspires in Formica.**
  - The `dead-end` pheromone channel is a direct port of the
    dead-end non-marking rule: when a Forager's evidence is rejected
    by a Validator, the edge it walked is marked `dead-end` rather
    than reinforced as `promising`.
  - The alarm pheromone (short half-life, preempts work) plays the
    role of rapid bidirectional search around a break: when an
    alarm lands on a subproblem, agents retreat and alternative
    branches are reweighted upward.
  - The "no backtracking" constraint maps to Formica's rule that an
    agent cannot immediately re-walk the edge it came in on during
    a single task.

### The Anternet: harvester ant traffic control

- Prabhakar, B., Dektar, K., Gordon, D. M. (2012). "The Regulation
  of Ant Colony Foraging Activity without Spatial Information."
  *PLoS Computational Biology* 8(8), e1002670. Reported for a
  general audience by Stanford Engineering as "Stanford biologist
  and computer scientist discover the 'anternet.'"
  [report](https://engineering.stanford.edu/news/stanford-biologist-and-computer-scientist-discover-anternet) ·
  [paper](https://doi.org/10.1371/journal.pcbi.1002670)
- **What it contributes.** Shows that harvester-ant foraging
  activity is regulated by the rate at which returning foragers
  arrive at the nest, in a feedback loop mathematically equivalent
  to TCP congestion control. Foragers slow their outbound rate when
  the return rate drops, which is exactly the additive-increase /
  multiplicative-decrease pattern on the Internet.
- **Seen elsewhere.** TCP itself. The AIMD family more broadly
  (CUBIC, BBR's probing behavior). The autoscaler in HPA with
  target-utilization.
- **Inspires in Formica.**
  - `formica/coordinator/anternet.py` - the "anternet signal" that
    scales spawn rate based on the recent ratio of validated
    evidence mass to compute-seconds consumed. Named after this
    paper explicitly.
  - The controller's backpressure rule ("if pending pods exceed
    threshold, throttle spawn") is the multiplicative-decrease half
    of AIMD applied to caste pool sizes.

## Stigmergy and colony behavior

### Encounter Rate and Task Allocation in Harvester Ants

- Gordon, D. M., Mehdiabadi, N. J. (1999). *Behavioral Ecology and
  Sociobiology* 45, 370-377.
  [link](https://web.stanford.edu/~dmgordon/previous/GordonMehdiabadi1999.pdf)
- **What it contributes.** The empirical basis for what Formica
  calls "Gordon's rule." Shows that an individual ant's probability
  of switching tasks is driven by the *rate* of its brief antennal
  encounters with workers engaged in another task, not by any global
  signal or count. Ants cannot assess total colony state; local
  encounter rate is sufficient. This is the original no-central-
  control result for insect task allocation, and the paper the
  colony-behavior section of the Active Inferants paper below
  builds on.
- **Seen elsewhere.** Nothing in distributed systems cites this
  directly, but every gossip-based membership protocol implements
  the same idea: local rates of "I heard from X recently" drive
  global state estimates.
- **Inspires in Formica.**
  - The role-reallocation logic in `formica/capacity/pools.py`:
    agents re-specialize based on local encounter rates with peers
    of other castes, not on a global "we need more validators"
    signal. The "Gordon's rule" name in the README points here.
  - The alarm pheromone's short half-life is calibrated so that it
    behaves like an encounter rate: spikes quickly, decays quickly,
    pressures nearby agents into the "respond to failure" task
    without a dispatcher.

### Active Inferants: An Active Inference Framework for Ant Colony Behavior

- Friedman, D. A., Tschantz, A., Ramstead, M. J. D., Friston, K.,
  Constant, A. (2021). *Frontiers in Behavioral Neuroscience* 15,
  647732.
  [link](https://www.frontiersin.org/journals/behavioral-neuroscience/articles/10.3389/fnbeh.2021.647732/full)
- **What it contributes.** Recasts ant colony foraging as active
  inference: each ant minimizes free energy over a generative model
  of the environment, the colony's stigmergic traces collectively
  constitute an extended-cognition substrate, and multiscale
  Bayesian inference unifies nestmate-, colony-, and population-
  scale behaviors. Connects the stigmergy literature with the
  Friston / free-energy-principle program.
- **Seen elsewhere.** Predictive-coding models of perception,
  world-models in reinforcement learning (Dreamer, etc.), and the
  "belief propagation on a shared graph" pattern in probabilistic
  robotics.
- **Inspires in Formica.**
  - The distinction in `docs/architecture.md` between "local belief
    written to the graph" (what an agent records) and "colony
    belief emerging from the pheromone field" (what the controller
    and downstream agents read) is the nestmate / colony scale
    split from this paper.
  - The Validator's role as an inference step rather than a
    gatekeeper: it does not approve or reject in a single step; it
    emits a `validated` pheromone that accumulates, and consensus
    emerges from many Validators' contributions. This is the
    paper's "inference as accumulated evidence" framing.

### Evolution of self-organised division of labour driven by stigmergy in leaf-cutter ants

- Govoni, P. et al. (2022). *Scientific Reports* 12, 22338.
  [link](https://www.nature.com/articles/s41598-022-26324-6)
- **What it contributes.** Agent-based model of leaf-cutter
  arboreal foraging where task partitioning (droppers vs
  collectors) evolves from a generalist baseline via independent
  mutations in two probabilities (P\_D, P\_P). Shows task
  partitioning is favored in tall-tree environments and emerges
  without pleiotropy, simultaneous mutations, or morphological
  differentiation. Dropped leaves act as the stigmergic stimulus;
  cache dynamics form an integral-control loop with oscillations.
- **Seen elsewhere.** The evolutionary-origin-of-specialization
  result parallels arguments in the division-of-labour literature
  for robot swarms (e.g. the "threshold reinforcement" family of
  models).
- **Inspires in Formica.**
  - Evidence in the Forum plays the role of "dropped leaves":
    Foragers produce, Validators consume, and the depth of the
    unvalidated-evidence queue is the integral-control signal that
    drives Gordon reallocation.
  - The Scout / Forager / Validator split is not hard-coded in
    principle - this paper is the argument that specialization can
    *evolve* from a generalist pool given the right cache dynamics.
    A future enhancement (tracked in project issues) would let pool
    sizes evolve from a single undifferentiated pool instead of
    being declared.

### Stigmergic construction and topochemical information shape ant nest architecture

- Khuong, A., Gautrais, J., Perna, A., Sbaï, C., Combe, M., Kuntz,
  P., Jost, C., Theraulaz, G. (2016). *PNAS* 113(5), 1303-1308.
  [link](https://pmc.ncbi.nlm.nih.gov/articles/PMC4747701/)
- **What it contributes.** Shows that *Lasius niger* nest
  architecture (regular pillar spacing, cap formation, arch
  merging) is fully explained by two interactions: a stigmergic
  amplification via pheromone-laced building material and a
  template interaction where ants use their body size as a height
  cue. 3D stochastic model reproduces field observations. Key
  parameter: pheromone lifetime. Too short, no structures; too
  long, saturation and merging collapse. Optimum is
  800-1,200 seconds for this species.
- **Seen elsewhere.** Procedural generation in games, morphogenesis
  models in biology (reaction-diffusion systems), and the
  "topological defects as structure" idea in condensed-matter
  physics.
- **Inspires in Formica.**
  - The six separate pheromone channels with *different* half-lives
    is a direct generalization of this paper's "pheromone lifetime
    controls form." Short half-life on `alarm` means alarm
    structures stay local; long half-life on `validated` means
    validated subgraphs persist as stable structure. The parameter
    tuning in `deploy/helm/formica/values.yaml` under `pheromones:`
    was calibrated against this paper's lifetime-vs-structure
    curves.
  - The template interaction (body size as a cue) has no Formica
    equivalent yet. A proposed feature (tracked in project issues)
    would use per-pool resource requests as a "body size" cue:
    Scouts with small resource requests naturally create different
    graph topology than Validators with larger ones.

## Formica-specific biology

These last two are not about computation at all, but they are what
justifies the "Formica" name over, say, "Atta" or "Pogonomyrmex."

### The evolution of social parasitism in Formica ants revealed by a global phylogeny

- Borowiec, M. L., Cover, S. P., Rabeling, C. (2021). *PNAS*
  118(38), e2026029118.
  [link](https://pubmed.ncbi.nlm.nih.gov/34535549/)
- **What it contributes.** Phylogeny of 172 *Formica* species
  showing that half are confirmed or suspected social parasites.
  Documents three parasitism classes (temporary, dulotic, permanent
  inquilinism), with permanent inquilinism evolving twice from
  temporary-parasite ancestors. Shows that obligate social
  parasitism can arise from a facultative-parasitism background via
  allopatric speciation.
- **Seen elsewhere.** The social-parasitism literature more broadly
  (cuckoos, brood parasites), but *Formica*'s diversity is
  unusually rich.
- **Inspires in Formica.**
  - The Inquiline caste (`formica/agents/inquiline/`) takes its
    name from this paper's "permanent inquilines" - narrow,
    specialized agents that live inside the colony and do one thing
    (citation checking, numeric sanity) without being part of the
    main scout-forager-validator flow.
  - The design freedom to add more Inquilines later without
    changing the main castes is modeled on how inquiline species
    in *Formica* integrate into host colonies without disrupting
    host caste structure.

### Untangling the Interplay Among Navigational Strategies Used by the Ant *Formica podzolica*

- Dias, C. M., Breed, M. D. (2008). *Annals of the Entomological
  Society of America* 101(6), 1145-1149.
  [link](https://academic.oup.com/aesa/article-abstract/101/6/1145/2758531)
- **What it contributes.** Shows that *Formica podzolica* foragers
  use multiple simultaneous navigation cues - pheromone trails,
  landmarks, compass bearings, visual scene snapshots, polarized
  light - rather than any single signal. Establishes that real ant
  navigation is multi-signal and context-dependent.
- **Seen elsewhere.** Sensor fusion in robotics, the "mixture of
  experts" pattern in ML, multi-modal retrieval in modern RAG
  systems.
- **Inspires in Formica.**
  - The six pheromone channels (rather than a single "weight")
    follow this paper's core insight: navigation is multi-signal.
    `promising`, `validated`, `risky`, `needs-expert`, `dead-end`,
    `alarm` are independent channels an agent can weigh
    differently based on caste and context.
  - The caste-specific attention weights (documented in
    `docs/pheromones.md`) implement the "weighted combination of
    signals" described in the paper's discussion.

## Also worth reading

### An experimental study of the foraging strategy of the wood ant *Formica rufa*

- Cherix, D. (1987). *Animal Behaviour* 35(5), 1520-1535.
  [link](https://www.sciencedirect.com/science/article/pii/S0003347285800774)
- Classic empirical grounding for foraging and recruitment behavior
  in *Formica rufa*, the species the genus is named after. Not
  directly cited by a specific Formica component, but sits behind
  the general shape of the Forager caste's recruitment behavior.

### Foraging Strategies of Ants (review)

- Traniello, J. F. A. (1989). *Annual Review of Entomology* 34,
  191-210.
  [link](https://www.annualreviews.org/doi/10.1146/annurev.en.34.010189.001203)
- Canonical review article surveying the full taxonomy of ant
  foraging strategies (solitary, tandem running, group recruitment,
  short-term trails, trunk trails, long-term networks, raiding).
  Useful context for anyone extending Formica with new caste types;
  most of the options have been field-tested by real ant species.
