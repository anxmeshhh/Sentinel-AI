"""LangGraph StateGraph: specialist agents fan into the Executive Agent.

Phase 1 shipped with one specialist node (engineering -> executive); the
Google module adds a second (communication -> executive), the first real use
of the N-node fan-out/fan-in shape the graph was built for from day one
(ARCHITECTURE.md §5). Each node only produces findings for the signal types
it understands - a Gmail connection's signals produce zero Engineering
candidates and a GitHub connection's signals produce zero Communication
candidates, so both nodes run unconditionally without needing to know which
connection triggered the run.

One agent node failing does not take down the run: its error is recorded in
`node_errors` and the graph continues with whatever findings the other nodes
produced (ARCHITECTURE.md §8, "partial failure is a first-class case").
"""

from typing import TypedDict

import structlog
from langgraph.graph import END, StateGraph

from app.agents.base import SpecialistAgent
from app.agents.communication_agent import CommunicationAgent
from app.agents.engineering_agent import EngineeringAgent
from app.agents.executive_agent import ExecutiveAgent
from app.models.finding import Finding
from app.models.signal import Signal

logger = structlog.get_logger("sentinel.graph")


class SentinelState(TypedDict, total=False):
    signals: list[Signal]
    connection_label: str
    findings: list[Finding]
    node_errors: dict[str, str]
    narrative: str
    top_finding_ids: list[str]


def _specialist_node_factory(agent: SpecialistAgent):
    def node(state: SentinelState) -> SentinelState:
        try:
            findings = agent.analyze(state.get("signals", []))
        except Exception as exc:  # a specialist agent's own bug must not kill the whole run
            logger.error("agent_node_failed", agent=agent.name, error=str(exc))
            node_errors = dict(state.get("node_errors", {}))
            node_errors[agent.name] = str(exc)
            return {"node_errors": node_errors}
        return {"findings": state.get("findings", []) + findings}

    return node


def _executive_node_factory(agent: ExecutiveAgent):
    def node(state: SentinelState) -> SentinelState:
        findings = state.get("findings", [])
        try:
            narrative, top_ids = agent.synthesize(findings, state.get("connection_label", ""))
        except Exception as exc:
            logger.error("agent_node_failed", agent=agent.name, error=str(exc))
            node_errors = dict(state.get("node_errors", {}))
            node_errors[agent.name] = str(exc)
            return {"node_errors": node_errors, "narrative": "", "top_finding_ids": []}
        return {"narrative": narrative, "top_finding_ids": top_ids}

    return node


def build_graph(
    engineering_agent: EngineeringAgent | None = None,
    communication_agent: CommunicationAgent | None = None,
    executive_agent: ExecutiveAgent | None = None,
):
    engineering_agent = engineering_agent or EngineeringAgent()
    communication_agent = communication_agent or CommunicationAgent()
    executive_agent = executive_agent or ExecutiveAgent()

    # Chained rather than concurrently fanned-out: both specialists append to
    # the same `findings` list in one execution thread, which sidesteps
    # LangGraph's parallel-branch state-merge reducers entirely - simplest
    # correct way to get the fan-in shape without a new class of merge bugs.
    graph = StateGraph(SentinelState)
    graph.add_node("engineering", _specialist_node_factory(engineering_agent))
    graph.add_node("communication", _specialist_node_factory(communication_agent))
    graph.add_node("executive", _executive_node_factory(executive_agent))
    graph.set_entry_point("engineering")
    graph.add_edge("engineering", "communication")
    graph.add_edge("communication", "executive")
    graph.add_edge("executive", END)
    return graph.compile()
