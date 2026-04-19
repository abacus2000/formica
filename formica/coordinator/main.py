"""Controller entrypoint. Wraps Controller.run_forever with a Forum-backed
entropy/validated-mass provider.
"""

from __future__ import annotations

from formica.blackboard.forum import Forum
from formica.capacity.pools import Pool
from formica.config import FormicaConfig
from formica.coordinator.controller import Controller
from formica.pheromones.decay import pheromone_entropy
from formica.telemetry.logs import get_logger
from formica.telemetry.otel import setup_otel

log = get_logger(__name__)


def default_pools(image: str = "formica:latest") -> list[Pool]:
    return [
        Pool(name="scout", image=image, min_replicas=1, max_replicas=4, priority=6),
        Pool(name="forager", image=image, min_replicas=2, max_replicas=16, priority=7),
        Pool(name="validator", image=image, min_replicas=1, max_replicas=8, priority=7),
        Pool(name="gc", image=image, min_replicas=0, max_replicas=2, priority=3),
        Pool(name="inquiline.citation", image=image, min_replicas=0, max_replicas=4, priority=4),
        Pool(name="inquiline.numeric", image=image, min_replicas=0, max_replicas=4, priority=4),
    ]


def _fetch_entropy_factory(forum: Forum):
    def _fetch():
        cypher = """
        MATCH ()-[r]->() WHERE r.pheromones IS NOT NULL
        UNWIND r.pheromones AS p
        RETURN p.channel AS channel, collect(coalesce(p.value, 0.0)) AS values
        """
        with forum._session() as s:  # noqa: SLF001
            by_channel = {r["channel"]: r["values"] for r in s.run(cypher)}
        entropy = pheromone_entropy(by_channel)
        validated_mass = sum(by_channel.get("validated", []))
        return validated_mass, entropy

    return _fetch


def main() -> None:
    cfg = FormicaConfig()
    setup_otel("controller", cfg)
    forum = Forum(cfg)
    forum.ensure_schema()
    ctrl = Controller(pools=default_pools(), config=cfg)
    log.info("controller starting", extra={"pools": [p.name for p in ctrl.pools]})
    ctrl.run_forever(_fetch_entropy_factory(forum))


if __name__ == "__main__":
    main()
