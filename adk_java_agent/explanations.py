from __future__ import annotations

import json
import sqlite3
import difflib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Explanation:
    agent: str
    step_kind: str
    reason: str
    change_summary: str
    files_changed: list[str]
    new_lines: int
    context: dict[str, object]
    diff_text: str = ""


class ExplanationStore:
    """SQLite store for code-change and design explanations."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS explanations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    step_kind TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    change_summary TEXT NOT NULL,
                    files_changed TEXT NOT NULL,
                    new_lines INTEGER NOT NULL,
                    context_json TEXT NOT NULL,
                    diff_text TEXT NOT NULL DEFAULT ''
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(explanations)")}
            if "diff_text" not in columns:
                conn.execute("ALTER TABLE explanations ADD COLUMN diff_text TEXT NOT NULL DEFAULT ''")

    def record(self, explanation: Explanation) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO explanations (
                    created_at, agent, step_kind, reason, change_summary,
                    files_changed, new_lines, context_json, diff_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    explanation.agent,
                    explanation.step_kind,
                    explanation.reason,
                    explanation.change_summary,
                    json.dumps(explanation.files_changed),
                    explanation.new_lines,
                    json.dumps(explanation.context, indent=2, sort_keys=True),
                    explanation.diff_text,
                ),
            )

    def list_all(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT id, created_at, agent, step_kind, reason, change_summary,
                           files_changed, new_lines, context_json, diff_text
                    FROM explanations
                    ORDER BY id
                    """
                )
            )


def count_new_lines(before: str | None, after: str) -> int:
    if before is None:
        return len(after.splitlines())
    before_lines = set(before.splitlines())
    return sum(1 for line in after.splitlines() if line not in before_lines)


def changed_files(paths: Iterable[Path], project_root: Path) -> list[str]:
    return [str(path.relative_to(project_root)) for path in paths]


def make_unified_diff(before: str | None, after: str, filename: str) -> str:
    before_lines = [] if before is None else before.splitlines()
    after_lines = after.splitlines()
    return "\n".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm="",
        )
    )
