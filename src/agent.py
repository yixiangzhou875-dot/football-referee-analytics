"""Step 3: an LLM agent that answers football questions by writing and running SQL.

How it works (an "agentic loop"):
  1. You ask a question in plain English.
  2. The model decides which tool to call: get_schema, run_sql or make_chart.
  3. Python runs the tool and sends the result back to the model.
  4. Steps 2-3 repeat until the model has enough to answer.

Run:
  pip install anthropic pandas matplotlib
  set ANTHROPIC_API_KEY=...        (Windows)   /   export ANTHROPIC_API_KEY=...  (Mac)
  python src/agent.py "Which referee gives the most yellow cards to away teams?"
  python src/agent.py              (interactive mode)
"""
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "football.db"
CHARTS = ROOT / "outputs" / "agent_charts"
MODEL = "claude-sonnet-5-5"
MAX_ROWS = 50
MAX_STEPS = 8

SYSTEM_PROMPT = """You are a football data analyst for Premier League refereeing data
(seasons 2015/16 to 2025/26, 4,180 matches). Answer the user's question with evidence.

Rules:
- Call get_schema first if you are unsure of table or column names.
- Use run_sql to get every number you report. Never guess numbers.
- Only compare referees with at least 50 matches unless the user asks otherwise; say so.
- Cards rose league-wide from 2023/24, so adjust for season when comparing referees across eras.
- If a query fails or returns something odd, fix the query and try again.
- Use make_chart when a comparison or trend is easier to see than to read.
- Finish with a short answer: 2-4 sentences, the key numbers, and one caveat."""

TOOLS = [
    {
        "name": "get_schema",
        "description": "Return the tables, views and columns in the football database.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_sql",
        "description": "Run one read-only SQLite SELECT query and return up to 50 rows as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A single SELECT statement"}},
            "required": ["query"],
        },
    },
    {
        "name": "make_chart",
        "description": "Run a SELECT query and save a bar or line chart of its result as a PNG.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SELECT returning an x column and a y column"},
                "x": {"type": "string"},
                "y": {"type": "string"},
                "kind": {"type": "string", "enum": ["bar", "line"]},
                "title": {"type": "string"},
            },
            "required": ["query", "x", "y", "kind", "title"],
        },
    },
]


# ---------------------------------------------------------------- tools ---
def _connect():
    # mode=ro opens the database read-only, so the model cannot change data.
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def _check_select(query: str) -> str:
    q = query.strip().rstrip(";")
    if ";" in q or not q.lower().lstrip("(").startswith(("select", "with")):
        raise ValueError("Only a single SELECT (or WITH ... SELECT) statement is allowed.")
    return q


def get_schema() -> str:
    with _connect() as con:
        rows = con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view')").fetchall()
        out = {}
        for name, kind in rows:
            cols = [c[1] for c in con.execute(f"PRAGMA table_info({name})")]
            out[f"{kind} {name}"] = cols
    return json.dumps(out)


def run_sql(query: str) -> str:
    with _connect() as con:
        df = pd.read_sql(_check_select(query), con)
    result = {"row_count": len(df), "rows": df.head(MAX_ROWS).to_dict(orient="records")}
    if len(df) > MAX_ROWS:
        result["note"] = f"Showing first {MAX_ROWS} rows; add ORDER BY/LIMIT or aggregate."
    return json.dumps(result, default=str)


def make_chart(query: str, x: str, y: str, kind: str, title: str) -> str:
    with _connect() as con:
        df = pd.read_sql(_check_select(query), con)
    CHARTS.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    if kind == "bar":
        ax.barh(df[x].astype(str), df[y], color="#1f4e79")
        ax.invert_yaxis()
        ax.set_xlabel(y)
    else:
        ax.plot(df[x].astype(str), df[y], marker="o", color="#1f4e79")
        ax.set_ylabel(y)
        ax.tick_params(axis="x", rotation=45)
    ax.set_title(title, loc="left")
    fig.tight_layout()
    path = CHARTS / f"chart_{datetime.now():%Y%m%d_%H%M%S}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return json.dumps({"saved_to": str(path), "points": len(df)})


TOOL_FUNCTIONS = {"get_schema": get_schema, "run_sql": run_sql, "make_chart": make_chart}


def call_tool(name: str, args: dict) -> tuple[str, bool]:
    """Run a tool; return (result, is_error). Errors go back to the model so it can fix its query."""
    try:
        return TOOL_FUNCTIONS[name](**args), False
    except Exception as e:  # noqa: BLE001 - any failure is reported to the model
        return f"Error: {e}", True


# ----------------------------------------------------------- agent loop ---
def ask(question: str, verbose: bool = True) -> str:
    import anthropic  # imported here so the tools above can be tested without the SDK

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    for _ in range(MAX_STEPS):
        response = client.messages.create(
            model=MODEL, max_tokens=2000, system=SYSTEM_PROMPT, tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        results = []
        for block in response.content:
            if block.type == "tool_use":
                if verbose:
                    print(f"  -> {block.name}: {json.dumps(block.input)[:160]}")
                output, is_error = call_tool(block.name, block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    return "Stopped: reached the maximum number of steps."


def main():
    if len(sys.argv) > 1:
        print(ask(" ".join(sys.argv[1:])))
        return
    print("Ask about Premier League referees (blank line to quit).")
    while (q := input("\n> ").strip()):
        print("\n" + ask(q))


if __name__ == "__main__":
    main()
