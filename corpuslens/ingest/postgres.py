"""Adapter: a PostgreSQL corpus — a table of turns reached via a connection
string (a libpq URL, a `key=value` conninfo, or a bare dbname).

ZERO Python dependencies, on purpose. corpuslens promises "nothing to install
beyond Python"; a `psycopg` import would break that. So this adapter shells out
to the `psql` CLIENT BINARY (the one system requirement, disclosed in the
README) and streams the corpus through a server-side `COPY … TO STDOUT` in CSV,
which the stdlib `csv` module parses — embedded newlines and quotes in message
text are handled by the format, not by fragile line-splitting.

Read-only by construction: the only statements issued are `SELECT`s and a
`COPY (SELECT …)`; the corpus is never written. Injection-safe: every identifier
that reaches SQL (schema, table, column) is escaped by doubling embedded
double-quotes — the correct escaping for a `"…"` identifier — so a maliciously
NAMED catalog table/schema/column (e.g. `t") TO STDOUT; DROP TABLE x; --`) cannot
break out of its quotes; and the `information_schema` lookups compare names as
escaped SQL string literals, never string-interpolated. (Catalog-matching a
`--table` argument is a usability check, not the security boundary — the escaping
is.) Columns are alias-resolved (see `_rows.py`); the wall applies
exactly as elsewhere — locators are host-free `"<table>:row<n>"`, hashed before
they reach an Event, and the calendar anchor is quarantined.
"""
from __future__ import annotations

import csv
import io
import subprocess

from ..failure_classes import describe as _describe_failure
from ..model import Surface
from . import register
from ._rows import (assemble, classify_role, parse_db_ts, require_columns,
                    resolve_columns)

_TABLE_PREFERENCE = ("turns", "messages", "events", "conversation", "conversations",
                     "chat", "chats", "log", "logs", "records", "sessions")
_TIMEOUT_S = 300


def _ident(name: str) -> str:
    """Quote a SQL identifier, doubling embedded double-quotes — the only correct
    escaping for a `"…"` identifier. This is what neutralizes a maliciously-named
    catalog table/schema/column; catalog-matching does not escape, it only
    validates existence."""
    return '"' + name.replace('"', '""') + '"'


def _lit(s: str) -> str:
    """A safe SQL string literal (standard_conforming_strings, the default):
    double embedded single-quotes. Used for the `information_schema` name
    comparisons so a name reaching SQL is a literal, never string-interpolated."""
    return "'" + s.replace("'", "''") + "'"


def _psql(dsn: str, sql: str, copy: bool = False) -> str:
    """Run one statement. Metadata queries use -tAc (tuples-only, unaligned);
    the corpus fetch uses a plain -c so `COPY … TO STDOUT` streams to stdout."""
    args = ["psql", dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1"]
    args += ["-c", sql] if copy else ["-tAc", sql]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=_TIMEOUT_S)
    except FileNotFoundError:
        raise RuntimeError(
            "the postgres adapter requires the `psql` client binary on PATH "
            "(corpuslens keeps zero Python dependencies by shelling out to it)")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"psql timed out after {_TIMEOUT_S}s")
    if proc.returncode != 0:
        # NEVER interpolate `proc.stderr` here. psql echoes the whole connection
        # URI back on a URI parse error, so this line used to print the
        # operator's database password in plaintext. `describe` reads that text
        # to classify it and returns only a closed-vocabulary phrase — see
        # corpuslens/failure_classes.py for the rule and what it costs.
        raise ValueError(_describe_failure("psql", proc.stderr))
    return proc.stdout


def _catalog_tables(dsn: str):
    out = _psql(dsn,
                "SELECT table_schema || chr(9) || table_name "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
                "AND table_type='BASE TABLE' ORDER BY table_schema, table_name")
    pairs = []
    for ln in out.splitlines():
        if "\t" in ln:
            sch, tbl = ln.split("\t", 1)
            pairs.append((sch, tbl))
    return pairs


def _resolve_table(dsn: str, table: str | None):
    pairs = _catalog_tables(dsn)
    if not pairs:
        raise ValueError("no base tables found for this connection")
    if table:
        want_sch, want_tbl = (table.split(".", 1) if "." in table else (None, table))
        hits = [(s, t) for (s, t) in pairs
                if t == want_tbl and (want_sch is None or s == want_sch)]
        if not hits:
            raise ValueError(f"table {table!r} not found; candidates: "
                             f"{[f'{s}.{t}' for s, t in pairs]}")
        if len(hits) > 1:
            raise ValueError(f"{table!r} is ambiguous across schemas "
                             f"{[s for s, _ in hits]}; qualify as schema.table")
        return hits[0]
    if len(pairs) == 1:
        return pairs[0]
    for pref in _TABLE_PREFERENCE:
        hits = [(s, t) for s, t in pairs if t.lower() == pref]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:                          # same preferred name in N schemas
            raise ValueError(f"table {pref!r} exists in multiple schemas "
                             f"{[s for s, _ in hits]}; qualify as schema.table")
    raise ValueError(f"{len(pairs)} base tables and no obvious corpus table — "
                     f"pass --table. Candidates: {[f'{s}.{t}' for s, t in pairs]}")


def _columns(dsn: str, schema: str, table: str):
    out = _psql(dsn,
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema = {_lit(schema)} AND table_name = {_lit(table)} "
                "ORDER BY ordinal_position")
    return [c for c in out.splitlines() if c]


@register("postgres", source="dsn")
def ingest(dsn: str, corpus_id: str = "corpus", table: str | None = None):
    schema, tbl = _resolve_table(dsn, table)
    cols = _columns(dsn, schema, tbl)
    if not cols:
        raise ValueError(f"no columns for {schema}.{tbl}")
    m = resolve_columns(cols)
    require_columns(m, f"{schema}.{tbl}", cols)

    sess_expr = f'{_ident(m["session"])}::text' if m["session"] else "''"
    select = (f'SELECT {_ident(m["ts"])}::text, {_ident(m["role"])}::text, '
              f'{_ident(m["content"])}::text, {sess_expr} '
              f'FROM {_ident(schema)}.{_ident(tbl)}')
    stream = _psql(dsn, f"COPY ({select}) TO STDOUT WITH (FORMAT csv)", copy=True)

    raw = []
    dropped = 0
    for n, rec in enumerate(csv.reader(io.StringIO(stream))):
        if len(rec) != 4:
            dropped += 1
            continue
        ts_s, role_s, content_s, sess_s = rec
        d, epoch = parse_db_ts(ts_s)
        if d is None:
            dropped += 1
            continue
        role = classify_role(role_s)
        if role is None:
            dropped += 1
            continue
        raw.append((d, epoch, sess_s or "_all", role, content_s, f"{tbl}:row{n}"))

    events, q, drop2 = assemble(raw, corpus_id, "postgres/1", Surface.DB)
    return events, q, dropped + drop2
