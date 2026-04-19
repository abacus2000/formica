"""Agent castes."""

from formica.agents.base import Agent, AgentResult
from formica.agents.scout import Scout
from formica.agents.forager import Forager
from formica.agents.validator import Validator
from formica.agents.gc import GarbageCollector

__all__ = ["Agent", "AgentResult", "Scout", "Forager", "Validator", "GarbageCollector"]
