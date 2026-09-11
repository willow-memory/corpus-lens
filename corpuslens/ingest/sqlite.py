"""Adapter: a SQLite corpus — a `.db` FILE holding a table of turns.

Zero dependencies (stdlib `sqlite3`). The database is opened READ-ONLY
(`mode=ro`), so pointing the lens at a live store can never mutate it. Columns
are resolved by alias (ts / role / content / session — see `_rows.py`), so no
per-column configuration is needed for a conventional turns table; a database
with more than one table needs `--table` unless exactly one obvious candidate
exists.

Every row that cannot become an Event — unparseable timestamp, unrecognized
role, empty text — is COUNTED toward `dropped` and surfaced in the audit
sentence, nothing silently discarded. The wall applies exactly as for the file
adapters: the row locator is `"<table>:row<n>"` (host-free) and is hashed before
it reaches an Event; the calendar anchor is quarantined.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..model import Surface
from . import register
from ..failure_classes import classify as _classify_failure
from ._rows import (as_text, assemble, classify_role, parse_db_ts,
                    require_columns, resolve_columns)
from .drops import DropCounts, MISSING_TIMESTAMP, UNRECOGNIZED_ROLE

# When a db has several tables and none was named, prefer an obvious corpus one.
_TABLE_PREFERENCE = ("turns", "messages", "events", "conversation", "conversations",
                     "chat", "chats", "log", "logs", "records", "sessions")


def _pick_table(con) -> str:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    names = [r[0] for r in rows]
    if not names:
        raise ValueError("no tables in this SQLite database")
    if len(names) == 1:
        return names[0]
    for pref in _TABLE_PREFERENCE:
        for n in names:
            if n.lower() == pref:
                return n
    raise ValueError(
        f"{len(names)} tables and no obvious corpus table — pass --table. "
        f"Tables: {names}")


@register("sqlite", source="file")
def ingest(path: str, corpus_id: str = "corpus", table: str | None = None):
    p = Path(path)
    if p.exists() and p.is_dir():
        raise IsADirectoryError(
            f"the sqlite adapter takes a .db FILE, not a directory: {path}")
    if not p.exists():
        raise FileNotFoundError(f"no such SQLite file: {path}")

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        try:
            table = table or _pick_table(con)
            info = con.execute(f'PRAGMA table_info("{table}")').fetchall()
        except sqlite3.DatabaseError as e:
            # `path` is echoed because the operator typed it (same reasoning as
            # cli.py's `_empty_message`); sqlite3's own message is NOT, because
            # this repo did not author it and cannot bound what it carries.
            raise ValueError(
                f"not a readable SQLite database: {path} "
                f"({_classify_failure(str(e))})")
        cols = [r[1] for r in info]
        if not cols:
            raise ValueError(f"table {table!r} not found or has no columns")
        m = resolve_columns(cols)
        require_columns(m, table, cols)

        raw = []
        drops = DropCounts()
        for n, row in enumerate(con.execute(f'SELECT * FROM "{table}"')):
            d, epoch = parse_db_ts(row[m["ts"]])
            if d is None:
                drops.add(MISSING_TIMESTAMP)
                continue
            role = classify_role(row[m["role"]])
            if role is None:
                drops.add(UNRECOGNIZED_ROLE)
                continue
            sess = as_text(row[m["session"]]) if m["session"] else "_all"
            raw.append((d, epoch, sess or "_all", role,
                        as_text(row[m["content"]]), f"{table}:row{n}"))
    finally:
        con.close()

    events, q, drops2 = assemble(raw, corpus_id, "sqlite/1", Surface.DB)
    return events, q, drops.merge(drops2)
