from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .explanations import ExplanationStore


def render_html(store: ExplanationStore) -> str:
    rows = store.list_all()
    items = []
    for row in rows:
        files = ", ".join(json.loads(row["files_changed"]))
        context = html.escape(row["context_json"])
        items.append(
            f"""
            <article>
              <header>
                <span>#{row['id']}</span>
                <strong>{html.escape(row['agent'])}</strong>
                <em>{html.escape(row['step_kind'])}</em>
              </header>
              <p>{html.escape(row['reason'])}</p>
              <p><b>Change:</b> {html.escape(row['change_summary'])}</p>
              <p><b>Files:</b> {html.escape(files or 'none')} | <b>New lines:</b> {row['new_lines']}</p>
              <details><summary>Context</summary><pre>{context}</pre></details>
            </article>
            """
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ADK Java Agent Explanations</title>
  <style>
    :root {{ color-scheme: light; font-family: Arial, sans-serif; }}
    body {{ margin: 0; background: #f7f7f4; color: #1e2428; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px; }}
    h1 {{ font-size: 28px; margin: 0 0 18px; }}
    article {{ background: white; border: 1px solid #d7d9d6; border-radius: 8px; padding: 16px; margin: 12px 0; }}
    header {{ display: flex; gap: 12px; align-items: center; color: #50606a; }}
    strong {{ color: #1d3f5f; }}
    em {{ background: #e7efe7; border-radius: 999px; padding: 3px 8px; font-style: normal; }}
    pre {{ overflow: auto; background: #10212b; color: #e8f1f2; padding: 12px; border-radius: 6px; }}
  </style>
</head>
<body>
  <main>
    <h1>ADK Java Agent Explanations</h1>
    {''.join(items) if items else '<p>No explanations recorded yet.</p>'}
  </main>
</body>
</html>"""


class ExplanationHandler(BaseHTTPRequestHandler):
    store: ExplanationStore

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/explanations":
            rows = []
            for row in self.store.list_all():
                item = dict(row)
                item["files_changed"] = json.loads(item["files_changed"])
                item["context"] = json.loads(item.pop("context_json"))
                rows.append(item)
            body = json.dumps(rows, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = render_html(self.store).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browse the explanation database.")
    parser.add_argument("--db", required=True, help="Path to explanations.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ExplanationHandler.store = ExplanationStore(Path(args.db).resolve())
    server = ThreadingHTTPServer((args.host, args.port), ExplanationHandler)
    print(f"Serving explanations at http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
