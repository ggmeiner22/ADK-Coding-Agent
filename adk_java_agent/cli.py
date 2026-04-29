from __future__ import annotations

import argparse
from pathlib import Path

from .agents import AgentContext
from .coding_agents import build_java_coding_agent
from .explanations import ExplanationStore
from .tools import JavaToolConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ADK-style Java coding agent.")
    parser.add_argument("--task", required=True, help="Java coding task for the agent.")
    parser.add_argument("--project-root", default="runs/calculator-demo", help="Generated Java project directory.")
    parser.add_argument("--db", default=None, help="SQLite explanation database path.")
    parser.add_argument("--junit-jar", default=None, help="Path to junit-platform-console-standalone jar.")
    parser.add_argument("--simulate-tools", action="store_true", help="Use deterministic local test simulation.")
    parser.add_argument("--max-cycles", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    db_path = Path(args.db).resolve() if args.db else project_root / "explanations.sqlite"
    store = ExplanationStore(db_path)
    context = AgentContext(
        task=args.task,
        project_root=project_root,
        explanation_store=store,
        max_cycles=args.max_cycles,
    )
    agent = build_java_coding_agent(
        JavaToolConfig(
            junit_jar=Path(args.junit_jar).resolve() if args.junit_jar else None,
            simulate_tools=args.simulate_tools,
        ),
        max_cycles=args.max_cycles,
    )
    result = agent.run(context)
    print(result.message)
    print(f"success={result.success}")
    print(f"project_root={project_root}")
    print(f"explanations_db={db_path}")
    if result.escalation:
        print(f"escalation={result.escalation}")
    return 0 if result.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
