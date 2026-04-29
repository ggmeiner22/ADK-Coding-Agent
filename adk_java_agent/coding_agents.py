from __future__ import annotations

from pathlib import Path
import re

from .agents import AgentContext, AgentResult, CheckResultAndEscalate, LlmAgent, LoopAgent, SequentialAgent
from .explanations import Explanation, changed_files, count_new_lines, make_unified_diff
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
    source_path = context.project_root / "src" / "main" / "java" / "Calculator.java"
    before = source_path.read_text(encoding="utf-8") if source_path.exists() else None
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source = """public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }

    public int subtract(int a, int b) {
        return a - b;
    }
}
"""
    source_path.write_text(source, encoding="utf-8")
    source_file = str(source_path.relative_to(context.project_root))
    context.explanation_store.record(
        Explanation(
            agent="first-version",
            step_kind="modularization",
            reason="Use one small Calculator class because the requested task is a compact arithmetic API.",
            change_summary="Created initial production Java source with add and subtract.",
            files_changed=[source_file],
            new_lines=count_new_lines(before, source),
            context={"task": context.task},
            diff_text=make_unified_diff(before, source, source_file),
        )
    )
    context.explanation_store.record(
        Explanation(
            agent="first-version",
            step_kind="data_structure_selection",
            reason=(
                "Use primitive int parameters and return values instead of a collection or DTO because each "
                "Calculator operation has exactly two scalar operands and one scalar result."
            ),
            change_summary="Selected a stateless Java class with primitive method signatures.",
            files_changed=changed_files([source_path], context.project_root),
            new_lines=0,
            context={
                "task": context.task,
                "selected_structures": ["Calculator class", "int operands", "int result"],
                "rejected_structures": ["List<Integer>", "Map<String,Integer>", "operation DTO"],
            },
        )
    )
    return AgentResult(True, "Initial Java version created.")


def create_junit5_tests(context: AgentContext) -> AgentResult:
    test_path = context.project_root / "src" / "test" / "java" / "CalculatorTest.java"
    before = test_path.read_text(encoding="utf-8") if test_path.exists() else None
    test_path.parent.mkdir(parents=True, exist_ok=True)
    tests = """import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class CalculatorTest {
    private final Calculator calculator = new Calculator();

    @Test
    void addsNumbers() {
        assertEquals(7, calculator.add(3, 4));
    }

    @Test
    void subtractsNumbers() {
        assertEquals(2, calculator.subtract(6, 4));
    }

    @Test
    void multipliesNumbers() {
        assertEquals(42, calculator.multiply(6, 7));
    }

    @Test
    void dividesNumbers() {
        assertEquals(5, calculator.divide(20, 4));
    }

    @Test
    void rejectsDivisionByZero() {
        assertThrows(IllegalArgumentException.class, () -> calculator.divide(20, 0));
    }
}
"""
    test_path.write_text(tests, encoding="utf-8")
    test_file = str(test_path.relative_to(context.project_root))
    context.explanation_store.record(
        Explanation(
            agent="junit5-tests-devel",
            step_kind="test_design",
            reason="JUnit 5 tests define the expected behavior before each improvement cycle.",
            change_summary="Created CalculatorTest covering add, subtract, multiply, divide, and zero division.",
            files_changed=[test_file],
            new_lines=count_new_lines(before, tests),
            context={"cycle": context.cycle},
            diff_text=make_unified_diff(before, tests, test_file),
        )
    )
    context.explanation_store.record(
        Explanation(
            agent="junit5-tests-devel",
            step_kind="data_structure_selection",
            reason=(
                "Use one Calculator instance as a test fixture because the production class is stateless; "
                "individual test methods express each behavioral requirement without shared mutable data."
            ),
            change_summary="Selected a single fixture object and assertion methods for expected values/exceptions.",
            files_changed=changed_files([test_path], context.project_root),
            new_lines=0,
            context={
                "cycle": context.cycle,
                "selected_structures": ["Calculator fixture", "JUnit assertion calls"],
                "rejected_structures": ["parameter table", "mutable shared result list"],
            },
        )
    )
    return AgentResult(True, "JUnit 5 tests created.")


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

    source_path = context.project_root / "src" / "main" / "java" / "Calculator.java"
    before = source_path.read_text(encoding="utf-8") if source_path.exists() else ""
    missing = []
    if isinstance(tool_result, dict):
        missing = list(tool_result.get("missing_methods", []))
        missing.extend(_missing_methods_from_compiler_output(str(tool_result.get("message", ""))))
    missing = sorted(set(missing))

    source = before
    if "multiply" in missing and "int multiply(int a, int b)" not in source:
        source = source.replace(
            "\n}\n",
            """

    public int multiply(int a, int b) {
        return a * b;
    }
}
""",
        )
    if ("divide" in missing or "divide_zero_guard" in missing) and "int divide(int a, int b)" not in source:
        source = source.replace(
            "\n}\n",
            """

    public int divide(int a, int b) {
        if (b == 0) {
            throw new IllegalArgumentException("Division by zero is undefined.");
        }
        return a / b;
    }
}
""",
        )
    elif "divide_zero_guard" in missing and "if (b == 0)" not in source:
        source = source.replace(
            "    public int divide(int a, int b) {\n",
            "    public int divide(int a, int b) {\n        if (b == 0) {\n            throw new IllegalArgumentException(\"Division by zero is undefined.\");\n        }\n",
        )

    if source == before:
        return AgentResult(False, "No known repair rule matched the failure.", escalation="manual_review_required")

    source_path.write_text(source, encoding="utf-8")
    source_file = str(source_path.relative_to(context.project_root))
    context.explanation_store.record(
        Explanation(
            agent="improve-code-using-failures",
            step_kind="code_change",
            reason="Use failed test feedback as incremental context for the next code change.",
            change_summary="Added missing Calculator behavior: " + ", ".join(missing),
            files_changed=[source_file],
            new_lines=count_new_lines(before, source),
            context={"cycle": context.cycle, "failure": tool_result},
            diff_text=make_unified_diff(before, source, source_file),
        )
    )
    return AgentResult(True, "Code improved from test failures.")


def _missing_methods_from_compiler_output(message: str) -> list[str]:
    methods = re.findall(r"symbol:\s+method\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", message)
    supported_repairs = {"multiply", "divide"}
    return [method for method in methods if method in supported_repairs]
