from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JavaToolConfig:
    junit_jar: Path | None = None
    simulate_tools: bool = False


class JavaTestTool:
    """Runs Java/JUnit tests through a tool abstraction.

    In simulation mode, it validates the generated calculator methods without a
    JDK. In real mode, it shells out to `javac` and the JUnit Console Launcher.
    """

    def __init__(self, config: JavaToolConfig) -> None:
        self.config = config

    def run_tests(self, project_root: Path) -> dict[str, object]:
        if self.config.simulate_tools:
            return self._simulate(project_root)
        return self._run_real_junit(project_root)

    def _simulate(self, project_root: Path) -> dict[str, object]:
        source = project_root / "src" / "main" / "java" / "Calculator.java"
        if not source.exists():
            return {"success": False, "message": "Calculator.java is missing."}
        text = source.read_text(encoding="utf-8")
        missing = [
            method
            for method in ("add", "subtract", "multiply", "divide")
            if f"int {method}(int a, int b)" not in text
        ]
        if missing:
            return {
                "success": False,
                "message": "Missing methods required by JUnit tests: " + ", ".join(missing),
                "missing_methods": missing,
            }
        if "if (b == 0)" not in text:
            return {
                "success": False,
                "message": "divide should reject division by zero.",
                "missing_methods": ["divide_zero_guard"],
            }
        return {"success": True, "message": "Simulated JUnit 5 tests passed."}

    def _run_real_junit(self, project_root: Path) -> dict[str, object]:
        javac = shutil.which("javac")
        java = shutil.which("java")
        if javac is None or java is None:
            return {
                "success": False,
                "environment_error": True,
                "message": "A JDK is required: `javac` and `java` were not found on PATH.",
            }
        if self.config.junit_jar is None or not self.config.junit_jar.exists():
            return {
                "success": False,
                "environment_error": True,
                "message": "JUnit Console Standalone jar is required. Pass --junit-jar.",
            }

        build_dir = project_root / "build" / "classes"
        build_dir.mkdir(parents=True, exist_ok=True)
        sources = list((project_root / "src" / "main" / "java").glob("*.java"))
        tests = list((project_root / "src" / "test" / "java").glob("*.java"))
        compile_cmd = [
            javac,
            "-cp",
            str(self.config.junit_jar),
            "-d",
            str(build_dir),
            *[str(path) for path in sources + tests],
        ]
        compile_result = subprocess.run(
            compile_cmd,
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if compile_result.returncode != 0:
            return {
                "success": False,
                "message": compile_result.stderr or compile_result.stdout,
                "phase": "compile",
            }
        run_cmd = [
            java,
            "-jar",
            str(self.config.junit_jar),
            "execute",
            "--class-path",
            str(build_dir),
            "--scan-class-path",
        ]
        run_result = subprocess.run(
            run_cmd,
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
        )
        return {
            "success": run_result.returncode == 0,
            "message": run_result.stdout + run_result.stderr,
            "phase": "test",
        }
