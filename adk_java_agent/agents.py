from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from .explanations import ExplanationStore


@dataclass
class AgentResult:
    success: bool
    message: str
    stop_loop: bool = False
    escalation: str | None = None


@dataclass
class AgentContext:
    task: str
    project_root: Path
    explanation_store: ExplanationStore
    max_cycles: int = 20
    cycle: int = 0
    state: dict[str, object] = field(default_factory=dict)


class Agent(Protocol):
    name: str

    def run(self, context: AgentContext) -> AgentResult:
        ...


class LlmAgent:
    """Small ADK-like LLM agent wrapper.

    The callable can be deterministic for local demos or backed by a real LLM.
    """

    def __init__(self, name: str, behavior: Callable[[AgentContext], AgentResult]) -> None:
        self.name = name
        self._behavior = behavior

    def run(self, context: AgentContext) -> AgentResult:
        return self._behavior(context)


class SequentialAgent:
    def __init__(self, name: str, agents: list[Agent]) -> None:
        self.name = name
        self.agents = agents

    def run(self, context: AgentContext) -> AgentResult:
        last = AgentResult(success=True, message="No agents configured.")
        for agent in self.agents:
            last = agent.run(context)
            context.state["last_result"] = last
            if last.stop_loop or last.escalation:
                return last
        return last


class LoopAgent:
    def __init__(self, name: str, agents: list[Agent], max_cycles: int = 20) -> None:
        self.name = name
        self.agents = agents
        self.max_cycles = max_cycles

    def run(self, context: AgentContext) -> AgentResult:
        last = AgentResult(success=False, message="Loop did not run.")
        for cycle in range(1, self.max_cycles + 1):
            context.cycle = cycle
            for agent in self.agents:
                last = agent.run(context)
                context.state["last_result"] = last
                if last.stop_loop:
                    return last
                if last.escalation:
                    return last
        return AgentResult(
            success=False,
            message=f"Maximum cycle count reached ({self.max_cycles}).",
            stop_loop=True,
            escalation="max_cycles_reached",
        )


class CheckResultAndEscalate:
    name = "CheckResultAndEscalate"

    def run(self, context: AgentContext) -> AgentResult:
        tool_result = context.state.get("tool_result", {})
        if isinstance(tool_result, dict) and tool_result.get("success") is True:
            return AgentResult(True, "All tests passed.", stop_loop=True)
        if isinstance(tool_result, dict) and tool_result.get("environment_error"):
            return AgentResult(
                False,
                str(tool_result["message"]),
                stop_loop=True,
                escalation="environment_setup_required",
            )
        return AgentResult(False, "Tests still failing; continue improvement loop.")
