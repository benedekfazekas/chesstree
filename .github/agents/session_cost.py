#!/usr/bin/env python3
"""Report token, context, and time usage for one or more Copilot CLI sessions.

Also reads the Brainy Smurf run_log from the per-session DB (when present)
and prints the orchestration workflow alongside the token/time report.

Usage:
    python3 .github/agents/session_cost.py                    # last 10 sessions
    python3 .github/agents/session_cost.py <session-id>       # one session, full breakdown
    python3 .github/agents/session_cost.py --recent N         # last N sessions
    python3 .github/agents/session_cost.py --list             # list sessions with IDs
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

STORE_DB = Path.home() / ".copilot" / "session-store.db"
SESSION_STATE_DIR = Path.home() / ".copilot" / "session-state"

SUMMARY_QUERY = """
SELECT
    s.id,
    s.summary,
    s.created_at,
    e.model,
    count(*)                                   AS api_calls,
    sum(e.input_tokens)                        AS input_tokens,
    sum(e.cache_read_tokens)                   AS cache_read_tokens,
    sum(e.cache_write_tokens)                  AS cache_write_tokens,
    sum(e.output_tokens)                       AS output_tokens,
    sum(e.reasoning_tokens)                    AS reasoning_tokens,
    round(sum(e.duration_ms) / 1000.0, 1)     AS total_sec
FROM assistant_usage_events e
JOIN sessions s ON e.session_id = s.id
{where}
GROUP BY s.id, e.model
ORDER BY s.created_at DESC, e.model
"""

LIST_QUERY = """
SELECT s.id, s.created_at, s.summary
FROM sessions s
WHERE EXISTS (SELECT 1 FROM assistant_usage_events e WHERE e.session_id = s.id)
ORDER BY s.created_at DESC
LIMIT ?
"""

RUN_LOG_QUERY = """
SELECT run_id, phase, round, agent, model, action, detail, ts
FROM run_log
ORDER BY id
"""


def connect_store() -> sqlite3.Connection:
    if not STORE_DB.exists():
        sys.exit(f"Session store DB not found: {STORE_DB}")
    return sqlite3.connect(STORE_DB)


def connect_session(session_id: str) -> sqlite3.Connection | None:
    db_path = SESSION_STATE_DIR / session_id / "session.db"
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "run_log" not in tables:
        conn.close()
        return None
    return conn


def fmt_tokens(n: int | None) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def fmt_time(total_sec: float | None) -> str:
    if total_sec is None:
        return "—"
    m, s = divmod(int(total_sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def cache_pct(cache_read: int, input_tokens: int) -> str:
    if not input_tokens:
        return "—"
    return f"{100.0 * cache_read / input_tokens:.0f}%"


def print_usage(rows: list[dict]) -> None:
    total_input = sum(r["input_tokens"] or 0 for r in rows)
    total_cache_read = sum(r["cache_read_tokens"] or 0 for r in rows)
    total_cache_write = sum(r["cache_write_tokens"] or 0 for r in rows)
    total_output = sum(r["output_tokens"] or 0 for r in rows)
    total_reasoning = sum(r["reasoning_tokens"] or 0 for r in rows)
    total_calls = sum(r["api_calls"] or 0 for r in rows)
    total_sec = sum(r["total_sec"] or 0.0 for r in rows)

    W = 22
    print(f"\n  Token & time breakdown by model")
    print(f"  {'Model':<{W}} {'Calls':>6} {'Input':>8} {'CacheRead':>10} {'CacheWrite':>11} {'Output':>8} {'Time':>8}  {'Cache%':>7}")
    print(f"  {'─'*W} {'─'*6} {'─'*8} {'─'*10} {'─'*11} {'─'*8} {'─'*8}  {'─'*7}")
    for r in rows:
        print(
            f"  {r['model']:<{W}} {r['api_calls']:>6} "
            f"{fmt_tokens(r['input_tokens']):>8} "
            f"{fmt_tokens(r['cache_read_tokens']):>10} "
            f"{fmt_tokens(r['cache_write_tokens']):>11} "
            f"{fmt_tokens(r['output_tokens']):>8} "
            f"{fmt_time(r['total_sec']):>8}  "
            f"{cache_pct(r['cache_read_tokens'] or 0, r['input_tokens'] or 0):>7}"
        )
    print(f"  {'─'*W} {'─'*6} {'─'*8} {'─'*10} {'─'*11} {'─'*8} {'─'*8}  {'─'*7}")
    print(
        f"  {'TOTAL':<{W}} {total_calls:>6} "
        f"{fmt_tokens(total_input):>8} "
        f"{fmt_tokens(total_cache_read):>10} "
        f"{fmt_tokens(total_cache_write):>11} "
        f"{fmt_tokens(total_output):>8} "
        f"{fmt_time(total_sec):>8}  "
        f"{cache_pct(total_cache_read, total_input):>7}"
    )

    notes = []
    if total_reasoning:
        notes.append(f"reasoning tokens: {fmt_tokens(total_reasoning)}")
    notes.append(
        f"context pressure: {fmt_tokens(total_cache_write)} tokens written to cache, "
        f"{cache_pct(total_cache_read, total_input)} of input served from cache"
    )
    for note in notes:
        print(f"\n  {note}")


def print_run_log(session_conn: sqlite3.Connection) -> None:
    rows = session_conn.execute(RUN_LOG_QUERY).fetchall()
    if not rows:
        return

    print(f"\n  Orchestration log (Brainy run_log)")
    print(f"  {'Time':<20} {'Run':<16} {'Ph':<12} {'Rnd':>3} {'Agent':<12} {'Action':<16}  Detail")
    print(f"  {'─'*20} {'─'*16} {'─'*12} {'─'*3} {'─'*12} {'─'*16}  {'─'*30}")
    for run_id, phase, round_, agent, model, action, detail, ts in rows:
        ts_fmt = (ts or "")[:16]
        run_short = (run_id or "")[:16]
        print(
            f"  {ts_fmt:<20} {run_short:<16} {(phase or ''):<12} {(round_ or 0):>3} "
            f"{(agent or ''):<12} {(action or ''):<16}  {(detail or '')}"
        )


def print_session(rows: list[dict], session_conn: sqlite3.Connection | None) -> None:
    if not rows:
        return

    sid = rows[0]["id"]
    summary = rows[0]["summary"] or "(no summary)"
    created = rows[0]["created_at"][:16].replace("T", " ")

    print(f"\n{'═'*70}")
    print(f"  Session : {sid}")
    print(f"  Created : {created}")
    print(f"  Summary : {summary}")
    print(f"{'═'*70}")

    print_usage(rows)

    if session_conn is not None:
        print_run_log(session_conn)
    else:
        print(f"\n  (no run_log found — session predates Brainy logging, or not an orchestrated session)")


def run_list(conn: sqlite3.Connection, n: int) -> None:
    rows = conn.execute(LIST_QUERY, (n,)).fetchall()
    print(f"\n{'─'*92}")
    print(f"  {'Created':<17} {'Session ID':<38}  Summary")
    print(f"{'─'*92}")
    for sid, created, summary in rows:
        has_log = (SESSION_STATE_DIR / sid / "session.db").exists()
        marker = " *" if has_log else "  "
        print(f"{marker} {(created or '').replace('T',' ')[:16]:<17} {sid:<38}  {(summary or '')[:45]}")
    print(f"\n  * = has per-session DB (may contain run_log)")


def fetch_rows(conn: sqlite3.Connection, where: str, params: list) -> list[dict]:
    cols = ["id", "summary", "created_at", "model", "api_calls",
            "input_tokens", "cache_read_tokens", "cache_write_tokens",
            "output_tokens", "reasoning_tokens", "total_sec"]
    cursor = conn.execute(SUMMARY_QUERY.format(where=where), params)
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def group_by_session(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["id"], []).append(r)
    return grouped


def main() -> None:
    parser = argparse.ArgumentParser(description="Copilot CLI session usage report")
    parser.add_argument("session_id", nargs="?", help="Session UUID to inspect")
    parser.add_argument("--recent", type=int, default=10, metavar="N",
                        help="Show last N sessions (default: 10)")
    parser.add_argument("--list", action="store_true", help="List recent sessions and exit")
    args = parser.parse_args()

    store = connect_store()

    if args.list:
        run_list(store, args.recent)
        return

    if args.session_id:
        rows = fetch_rows(store, "WHERE s.id = ?", [args.session_id])
        if not rows:
            sys.exit(f"Session not found: {args.session_id}")
        session_conn = connect_session(args.session_id)
        print_session(rows, session_conn)
        if session_conn:
            session_conn.close()
    else:
        ids_rows = store.execute(LIST_QUERY, (args.recent,)).fetchall()
        ids = [r[0] for r in ids_rows]
        if not ids:
            sys.exit("No sessions found.")
        placeholders = ",".join("?" * len(ids))
        rows = fetch_rows(store, f"WHERE s.id IN ({placeholders})", ids)
        for sid, session_rows in group_by_session(rows).items():
            session_conn = connect_session(sid)
            print_session(session_rows, session_conn)
            if session_conn:
                session_conn.close()


if __name__ == "__main__":
    main()
