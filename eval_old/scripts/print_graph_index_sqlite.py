"""Print OpenClaw graph-index SQLite tables in a readable form."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_TABLES = (
    "projection_inbox",
    "source_projection_state",
    "event_records",
    "entity_states",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print graph-index sidecar SQLite tables for debugging."
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        help="Path to main.graph.sqlite. Defaults to $OPENCLAW_STATE_DIR/memory/main.graph.sqlite.",
    )
    parser.add_argument(
        "--state-dir",
        help="OpenClaw state dir used to resolve memory/main.graph.sqlite when db_path is omitted.",
    )
    parser.add_argument(
        "--table",
        action="append",
        choices=DEFAULT_TABLES,
        help="Table to print. May be passed multiple times. Defaults to all core graph tables.",
    )
    parser.add_argument("--limit", type=int, default=50, help="Maximum rows per table.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of a human-readable table view.",
    )
    parser.add_argument(
        "--include-entries",
        action="store_true",
        help="Include projection_inbox entries_json payloads. Hidden by default because it can contain chat text.",
    )
    return parser


def resolve_db_path(args: argparse.Namespace) -> Path:
    if args.db_path:
        return Path(args.db_path).expanduser()
    if args.state_dir:
        return Path(args.state_dir).expanduser() / "memory" / "main.graph.sqlite"
    raise SystemExit("Provide db_path or --state-dir.")


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})")]


def count_rows(con: sqlite3.Connection, table: str) -> int:
    row = con.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"] if row else 0)


def rowid_order_column(columns: list[str]) -> str:
    for column in ("created_at", "last_projected_at", "last_updated_at", "occurred_at"):
        if column in columns:
            return column
    return "rowid"


def load_rows(
    con: sqlite3.Connection,
    table: str,
    *,
    limit: int,
    include_entries: bool,
) -> list[dict[str, Any]]:
    columns = table_columns(con, table)
    selected_columns = list(columns)
    if table == "projection_inbox" and not include_entries:
        selected_columns = [column for column in selected_columns if column != "entries_json"]
    order_column = rowid_order_column(columns)
    query = (
        f"SELECT {', '.join(selected_columns)} FROM {table} "
        f"ORDER BY {order_column} DESC LIMIT ?"
    )
    return [dict(row) for row in con.execute(query, (limit,))]


def decode_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def simplify_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    simplified = dict(row)
    for key in ("entries_json", "supporting_event_ids"):
        if key in simplified:
            simplified[key] = decode_jsonish(simplified[key])
    if table == "event_records":
        simplified.pop("extractor_version", None)
    return simplified


def format_value(value: Any, *, width: int = 72) -> str:
    if value is None:
        text = ""
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > width:
        return text[: width - 1] + "…"
    return text


def print_human_table(table: str, rows: list[dict[str, Any]], total: int) -> None:
    print(f"\n## {table} ({len(rows)}/{total} rows shown)")
    if not rows:
        print("(empty)")
        return
    for index, row in enumerate(rows, start=1):
        print(f"\n[{index}]")
        for key, value in row.items():
            print(f"  {key}: {format_value(value)}")


def main() -> None:
    args = build_parser().parse_args()
    db_path = resolve_db_path(args)
    if not db_path.exists():
        raise SystemExit(f"Graph SQLite file does not exist: {db_path}")

    tables = tuple(args.table or DEFAULT_TABLES)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    output: dict[str, Any] = {"db_path": str(db_path), "tables": {}}
    for table in tables:
        if not table_exists(con, table):
            output["tables"][table] = {"exists": False, "rows": []}
            continue
        total = count_rows(con, table)
        rows = [
            simplify_row(table, row)
            for row in load_rows(
                con,
                table,
                limit=max(args.limit, 0),
                include_entries=args.include_entries,
            )
        ]
        output["tables"][table] = {"exists": True, "total": total, "rows": rows}

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    print(f"Graph SQLite: {db_path}")
    for table in tables:
        data = output["tables"][table]
        if not data["exists"]:
            print(f"\n## {table}\n(missing)")
            continue
        print_human_table(table, data["rows"], int(data["total"]))


if __name__ == "__main__":
    main()
