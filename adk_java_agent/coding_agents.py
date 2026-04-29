from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agents import AgentContext, AgentResult, CheckResultAndEscalate, LlmAgent, LoopAgent, SequentialAgent
from .explanations import Explanation, count_new_lines, make_unified_diff
from .llm import parse_json_response
from .tools import JavaTestTool, JavaToolConfig


def build_java_coding_agent(tool_config: JavaToolConfig, max_cycles: int = 20) -> SequentialAgent:
    test_tool = JavaTestTool(tool_config)
    return SequentialAgent(
        "SequentialAgent",
        [
            LlmAgent("first-version", create_first_version),
            LoopAgent(
                "LoopAgent",
                [
                    LlmAgent("junit5-tests-devel", create_junit5_tests),
                    LlmAgent("run-unit-tests-with-mcp-tools", lambda context: run_unit_tests(context, test_tool)),
                    LlmAgent("improve-code-using-failures", improve_code_using_failures),
                    CheckResultAndEscalate(),
                ],
                max_cycles=max_cycles,
            ),
        ],
    )


def create_first_version(context: AgentContext) -> AgentResult:
    response = _ask_json(context, _first_version_prompt(context.task))
    changed = _apply_llm_file_response(context, "first-version", response)
    context.state["generated_files"] = changed
    return AgentResult(True, f"Initial Java version created with {len(changed)} file(s).")


def create_junit5_tests(context: AgentContext) -> AgentResult:
    response = _ask_json(context, _test_generation_prompt(context))
    changed = _apply_llm_file_response(context, "junit5-tests-devel", response)
    context.state["test_files"] = changed
    return AgentResult(True, f"JUnit 5 tests created with {len(changed)} file(s).")


def run_unit_tests(context: AgentContext, test_tool: JavaTestTool) -> AgentResult:
    result = test_tool.run_tests(context.project_root)
    context.state["tool_result"] = result
    context.explanation_store.record(
        Explanation(
            agent="run-unit-tests-with-mcp-tools",
            step_kind="tool_execution",
            reason="Compile and execute tests after each generated change to convert feedback into context.",
            change_summary=str(result.get("message", ""))[:500],
            files_changed=[],
            new_lines=0,
            context={"cycle": context.cycle, "tool_result": result},
        )
    )
    return AgentResult(bool(result.get("success")), str(result.get("message", "")))


def improve_code_using_failures(context: AgentContext) -> AgentResult:
    tool_result = context.state.get("tool_result", {})
    if isinstance(tool_result, dict) and tool_result.get("success"):
        return AgentResult(True, "No improvement needed.")
    if isinstance(tool_result, dict) and tool_result.get("environment_error"):
        return AgentResult(False, str(tool_result["message"]), escalation="environment_setup_required")

    response = _ask_json(context, _improvement_prompt(context, tool_result))
    changed = _apply_llm_file_response(context, "improve-code-using-failures", response)
    if not changed:
        return AgentResult(False, "LLM did not return any file changes.", escalation="manual_review_required")
    return AgentResult(True, f"Code improved with {len(changed)} file change(s).")


def _ask_json(context: AgentContext, prompt: str) -> dict[str, Any]:
    raw = context.llm.generate(prompt)
    response = parse_json_response(raw)
    if "files" not in response or not isinstance(response["files"], list):
        raise ValueError("LLM JSON must contain a files array.")
    return response


def _apply_llm_file_response(context: AgentContext, agent_name: str, response: dict[str, Any]) -> list[str]:
    changed_files = []
    file_diffs = {}
    for item in response["files"]:
        if not isinstance(item, dict):
            raise ValueError("Each file entry must be an object.")
        relative_path = _validate_generated_path(str(item.get("path", "")))
        content = str(item.get("content", ""))
        target = context.project_root / relative_path
        before = target.read_text(encoding="utf-8") if target.exists() else None
        if before == content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        changed_files.append(relative_path)
        file_diffs[relative_path] = {
            "before": before,
            "after": content,
            "diff": make_unified_diff(before, content, relative_path),
            "new_lines": count_new_lines(before, content),
        }

    explanations = response.get("explanations", [])
    if not isinstance(explanations, list):
        explanations = []
    if not explanations and changed_files:
        explanations = [
            {
                "step_kind": "code_change",
                "reason": "The LLM returned file changes for the current agent step.",
                "change_summary": "Updated generated Java project files.",
                "files": changed_files,
            }
        ]

    for explanation in explanations:
        if not isinstance(explanation, dict):
            continue
        files = [path for path in explanation.get("files", changed_files) if path in changed_files]
        if not files and changed_files:
            files = changed_files
        new_lines = sum(file_diffs[path]["new_lines"] for path in files)
        diff_text = "\n".join(file_diffs[path]["diff"] for path in files if file_diffs[path]["diff"])
        context.explanation_store.record(
            Explanation(
                agent=agent_name,
                step_kind=str(explanation.get("step_kind", "code_change")),
                reason=str(explanation.get("reason", "No reason supplied by LLM.")),
                change_summary=str(explanation.get("change_summary", "Updated generated files.")),
                files_changed=files,
                new_lines=new_lines,
                context={
                    "cycle": context.cycle,
                    "task": context.task,
                    "llm_explanation": explanation,
                    "response_notes": response.get("notes", ""),
                },
                diff_text=diff_text,
            )
        )
    return changed_files


def _validate_generated_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    if not normalized:
        raise ValueError("Generated file path cannot be empty.")
    candidate = Path(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Generated file path must be relative and stay inside the project: {path}")
    allowed_prefixes = ("src/main/java/", "src/test/java/")
    if not normalized.startswith(allowed_prefixes):
        raise ValueError(f"Generated Java files must be under src/main/java or src/test/java: {path}")
    return normalized


def _current_project_snapshot(project_root: Path) -> str:
    snapshots = []
    for root in ("src/main/java", "src/test/java"):
        base = project_root / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.java")):
            relative = path.relative_to(project_root).as_posix()
            snapshots.append(f"FILE: {relative}\n```java\n{path.read_text(encoding='utf-8')}\n```")
    return "\n\n".join(snapshots) or "No Java files exist yet."


def _json_contract() -> str:
    return """
Return only JSON with this shape:
{
  "files": [
    {"path": "src/main/java/Example.java", "content": "complete file contents"}
  ],
  "explanations": [
    {
      "step_kind": "modularization | data_structure_selection | test_design | code_change",
      "reason": "why this decision/change was made",
      "change_summary": "short human-readable summary",
      "files": ["src/main/java/Example.java"]
    }
  ],
  "notes": "optional short note"
}

Rules:
- Return complete file contents, not patches.
- Put production Java under src/main/java.
- Put JUnit 5 tests under src/test/java.
- Use no package declaration unless the task explicitly asks for one.
- Include at least one modularization explanation when creating production code.
- Include at least one data_structure_selection explanation when choosing classes, fields, collections, or method signatures.
- Do not wrap the JSON in Markdown.
""".strip()


def _first_version_prompt(task: str) -> str:
    return f"""
You are the first-version LlmAgent in a sequential Java coding agent.

Create the initial Java production code for this task:
{task}

Do not create tests in this step. Create a small, compilable first version that a later JUnit agent can test.

{_json_contract()}
""".strip()


def _test_generation_prompt(context: AgentContext) -> str:
    return f"""
You are the JUnit 5 test-development LlmAgent.

Task:
{context.task}

Current project:
{_current_project_snapshot(context.project_root)}

Create JUnit 5 tests that specify the expected behavior. The tests should be strong enough to expose missing or incorrect production code.

{_json_contract()}
""".strip()


def _improvement_prompt(context: AgentContext, tool_result: object) -> str:
    return f"""
You are the improve-code-using-failures LlmAgent.

Task:
{context.task}

Current project:
{_current_project_snapshot(context.project_root)}

The compile/test tool returned this feedback:
```json
{json.dumps(tool_result, indent=2)}
```

Update the Java files to fix the failures. You may update production code or tests only when the tests are incorrect for the task.

{_json_contract()}
""".strip()
