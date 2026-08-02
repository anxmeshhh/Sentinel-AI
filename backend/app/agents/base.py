"""Shared contract every specialist agent implements (ARCHITECTURE.md §4).

`analyze()` is always called with pre-computed metrics, never raw signal
dumps - keeps token usage low and keeps the LLM's job to narrative +
confidence scoring, not statistics.
"""

from abc import ABC, abstractmethod

from app.models.finding import AgentFinding
from app.models.signal import Signal


class SpecialistAgent(ABC):
    name: str

    @abstractmethod
    def analyze(self, signals: list[Signal]) -> list[AgentFinding]:
        """Turn a window of signals into zero or more Findings."""
        raise NotImplementedError
