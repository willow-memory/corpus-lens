"""corpuslens CLI.

    corpuslens run <path> --adapter claude-code [--format markdown|json]
    corpuslens doctor <path> --adapter claude-code      # what would be read, and what dropped
    corpuslens adapters                                 # what can be read, and from what
    corpuslens analyzers                                # what gets computed, and out of what
    corpuslens diff a.json b.json                       # the delta between two --format json runs

Every subcommand runs under the DEFAULT profile: no calendar, no timezone, no
person claims. There is deliberately no CLI flag to grant capabilities — a
grant is an owner-side code change (a Profile constructed in your own script),
not a switch someone can flip in a command line they found in a README.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import diff as diffmod
from . import ingest, render
from .analyze import all_analyzers
from .guard import DEFAULT_PROFILE, Guard, WallError

SOURCE_HELP = {
    "file": "a single file (e.g. a SQLite .db)",
    "dsn": "a connection string, not a filesystem path",
}


def _expects(adapter: str) -> str:
    src = ingest.source_of(adapter)
    if src == "dir":
        return f"a directory tree of {ingest.pattern_of(adapter)} session files"
    return SOURCE_HELP.get(src, "")


def _check_path(path: str, adapter: str, src: str):
    """Validate the positional argument against the adapter's source kind.
    Returns (n_matching_files, error_message|None)."""
    p = Path(path)
    if src == "dsn":
        return 0, None      # no filesystem check — the adapter validates the connection
    if not p.exists():
        return 0, f"path does not exist: {path}"
    if src == "dir":
        pat = ingest.pattern_of(adapter)
        if not p.is_dir():
            return 0, (f"expected a directory of {pat} session files, got a file: {path}\n"
                       f"       point corpuslens at the parent directory, not a single session file.")
        return sum(1 for f in p.rglob(pat) if f.is_file()), None
    if p.is_dir():
        return 0, f"adapter '{adapter}' expects a single file, got a directory: {path}"
    return 0, None


def _ingest(path: str, adapter: str, table: str | None):
    """(events, quarantine, dropped, n_files) or raises ValueError with a
    ready-to-print message. Shared by `run` and `doctor` so the two can never
    disagree about what a corpus contains."""
    src = ingest.source_of(adapter)
    n_files, err = _check_path(path, adapter, src)
    if err:
        raise ValueError(err)
    kw = {"table": table} if (table is not None and src in ("file", "dsn")) else {}
    events, quarantine, dropped = ingest.get(adapter)(path, **kw)
    return events, quarantine, dropped, n_files


def _empty_message(path, adapter, src, n_files, dropped) -> str:
    pat = ingest.pattern_of(adapter)
    if src == "dir" and n_files == 0:
        return f"no {pat} files found under {path}. Wrong directory?"
    if src == "dir":
        return (f"{n_files} {pat} file(s) under {path} but none yielded a datable, "
                f"non-empty turn for adapter '{adapter}' (dropped {dropped}). Wrong adapter?")
    return (f"adapter '{adapter}' yielded no datable, non-empty turn from {path} "
            f"(dropped {dropped}). Wrong table/columns, or an empty corpus?")


def _window(events, since_day, until_day):
    """Filter to a RELATIVE-day window (day 0 = the corpus's first event, never a
    calendar date). Returns (kept, n_excluded, clause|None). A window is a
    subset, and the audit sentence says so — filtered numbers are not corpus
    numbers."""
    if since_day is None and until_day is None:
        return events, 0, None
    lo = since_day if since_day is not None else -(10 ** 9)
    hi = until_day if until_day is not None else 10 ** 9
    kept = [e for e in events if lo <= e.time.day_offset <= hi]
    lo_s = "corpus start" if since_day is None else str(since_day)
    hi_s = "corpus end" if until_day is None else str(until_day)
    return kept, len(events) - len(kept), f"relative-day window {lo_s}..{hi_s}, inclusive"


def run(path: str, adapter: str, out: str | None, table: str | None = None,
        fmt: str = "markdown", since_day: int | None = None,
        until_day: int | None = None) -> int:
    src = ingest.source_of(adapter)
    try:
        events, quarantine, dropped, n_files = _ingest(path, adapter, table)
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, ValueError,
            RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not events:
        print(f"error: {_empty_message(path, adapter, src, n_files, dropped)}", file=sys.stderr)
        return 1

    events, n_filtered, clause = _window(events, since_day, until_day)
    if not events:
        print(f"error: the --since-day/--until-day window ({clause}) excluded every event "
              f"({n_filtered} dropped by the window). Widen it.", file=sys.stderr)
        return 1

    guard = Guard(quarantine, DEFAULT_PROFILE)
    guard.audit.n_events = len(events)
    guard.audit.n_dropped = dropped
    guard.audit.adapter = adapter
    if clause:
        guard.audit.filters.append(clause)
        guard.audit.n_filtered = n_filtered

    results = {}
    for a in all_analyzers():
        if not guard.admit(a):
            continue
        results[a.name] = {"denominator": a.denominator, "analyzer_version": a.version,
                          **a.run(events)}
        guard.audit.analyzers_run.append(a.name)
    report = render.render(fmt, results, guard.audit)
    try:
        report = guard.scan_egress(report)   # fail-closed backstop at the output door
    except WallError as e:
        # A quarantined value reached the rendered report. Do NOT emit it —
        # refuse loudly. The report is discarded, not printed.
        print(f"error: {e}", file=sys.stderr)
        return 3
    if out:
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(report)
        except OSError as e:
            print(f"error: could not write --out {out}: {e}", file=sys.stderr)
            return 2
        print(f"wrote {out}")
    else:
        print(report)
    return 0


def _diagnose(events, quarantine, dropped, adapter, src, n_files, path) -> dict:
    """Counts only — never content, never the anchor itself (only whether one
    was quarantined). Split out from `doctor` so the numbers and their
    rendering can be tested apart."""
    total = len(events) + dropped
    op = [e for e in events if e.author_class == "operator"]
    machine = [e for e in events if e.author_class == "machine"]
    threads = {e.thread_id for e in events}
    days = {e.time.day_offset for e in events}
    with_delta = sum(1 for e in events if e.time.delta_prev_s is not None)
    diag = {
        "adapter": adapter,
        "source_kind": src,
        "source_files_seen": n_files if src == "dir" else None,
        "source_file_pattern": ingest.pattern_of(adapter) if src == "dir" else None,
        "records_read": total,
        "events_kept": len(events),
        "events_dropped": dropped,
        "drop_pct": round(100 * dropped / total, 1) if total else 0.0,
        "operator_turns": len(op),
        "machine_turns": len(machine),
        "threads": len(threads),
        "relative_day_span": (max(days) - min(days) + 1) if days else 0,
        "turns_with_tempo_delta": with_delta,
        "anchor_quarantined": bool(quarantine.base_date_iso),
    }
    notes = []
    if not events:
        notes.append(_empty_message(path, adapter, src, n_files, dropped))
    if events and not machine:
        notes.append("no machine turns: `clarification_pull` cannot be computed on this corpus.")
    if events and not with_delta:
        notes.append("no within-day tempo deltas: `tempo` cannot be computed on this corpus "
                     "(a store that does not clock prompts, or one turn per thread per day).")
    if diag["drop_pct"] >= 50.0:
        notes.append(f"{diag['drop_pct']}% of records were dropped — check the adapter "
                     f"(and --table) before trusting any rate computed from the rest.")
    if not quarantine.base_date_iso and events:
        notes.append("no calendar anchor was quarantined for this corpus.")
    diag["notes"] = notes
    diag["reminder"] = ("diagnostics only — no analyzer ran, no rate was computed, and the "
                        "calendar anchor stayed quarantined.")
    return diag


def _render_doctor(diag: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(diag, indent=2, default=str)
    lines = ["# corpuslens doctor", ""]
    for k, v in diag.items():
        if k in ("notes", "reminder") or v is None:
            continue
        lines.append(f"- **{k}**: {v}")
    if diag["notes"]:
        lines += ["", "## notes"] + [f"- {n}" for n in diag["notes"]]
    lines += ["", f"*{diag['reminder']}*"]
    return "\n".join(lines)


def doctor(path: str, adapter: str, table: str | None = None, fmt: str = "markdown") -> int:
    """A dry run of ingestion only: what this adapter can see in this corpus,
    how much it had to drop, and which analyzers that corpus can actually feed
    — before committing to a report. Runs no analyzer and emits no rates.

    Same wall as `run`: relative days only, counts rather than content, and the
    output passes the same fail-closed egress scan — a diagnostic is an output
    door too, and must not be the quieter way out.
    """
    src = ingest.source_of(adapter)
    try:
        events, quarantine, dropped, n_files = _ingest(path, adapter, table)
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, ValueError,
            RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    diag = _diagnose(events, quarantine, dropped, adapter, src, n_files, path)
    text = _render_doctor(diag, fmt)
    try:
        text = Guard(quarantine, DEFAULT_PROFILE).scan_egress(text)
    except WallError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    print(text)
    return 0 if events else 1


def adapters(fmt: str = "markdown") -> int:
    rows = [{"adapter": name, "argument": ingest.source_of(name), "expects": _expects(name)}
            for name in ingest.available()]
    if fmt == "json":
        print(json.dumps(rows, indent=2))
    else:
        print("# corpuslens adapters")
        print()
        for r in rows:
            print(f"- **{r['adapter']}** — {r['expects']}")
        print()
        print("*Pass one with `--adapter`; the positional argument must be what it expects.*")
    return 0


def analyzers(fmt: str = "markdown") -> int:
    rows = [{"analyzer": a.name, "claims": list(a.claims), "denominator": a.denominator,
            "version": a.version}
            for a in all_analyzers()]
    if fmt == "json":
        print(json.dumps(rows, indent=2))
    else:
        print("# corpuslens analyzers")
        print()
        for r in rows:
            print(f"- **{r['analyzer']}** (v{r['version']}) — claims {', '.join(r['claims'])}; "
                  f"out of {r['denominator']}")
        print()
        print("*Every rate names its denominator, and every claim type is on the process-only "
              "allowlist in `model.py` — a person-shaped claim has no representation here. The "
              "version is the analyzer's SEMANTICS (classifiers/thresholds), not the JSON document "
              "shape — see `corpuslens.analyze.Analyzer` — and `corpuslens diff` withholds the "
              "delta for any analyzer whose version disagrees between the two runs.*")
    return 0


def diff_cmd(path_a: str, path_b: str, fmt: str = "markdown") -> int:
    """Compare two `corpuslens run --format json` files. Never a traceback:
    a malformed or non-corpuslens file is a clear `error:` line and a
    non-zero exit, same as every other subcommand's failure mode.

    Exit codes: 0 a diff was produced (it may still carry loud comparability
    warnings — read them); 1 the two runs were refused as not comparable at
    all (different adapter or schema_version — see corpuslens/diff.py); 2 a
    file could not be read as a corpuslens report.
    """
    try:
        doc_a = diffmod.load_report(path_a)
        doc_b = diffmod.load_report(path_b)
    except diffmod.DiffError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    result = diffmod.compare(doc_a, doc_b)
    renderer = diffmod.RENDERERS.get(fmt, diffmod.render_markdown)
    print(renderer(result))
    return 1 if result["refused"] else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="corpuslens")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_format(parser):
        parser.add_argument("--format", default="markdown", choices=render.available(),
                            dest="fmt", help="output format (default: markdown)")

    r = sub.add_parser("run", help="run the process battery on a corpus "
                                    "(a directory, a SQLite .db, or a Postgres DSN)")
    r.add_argument("path", help="directory of *.jsonl, a SQLite .db file, or a "
                                "Postgres connection string, per --adapter")
    r.add_argument("--adapter", required=True, choices=ingest.available())
    r.add_argument("--out", default=None)
    r.add_argument("--table", default=None,
                   help="db adapters only: the turns table (schema.table ok); "
                        "auto-detected when the db has one obvious candidate")
    r.add_argument("--since-day", type=int, default=None, metavar="N",
                   help="analyze only events on or after RELATIVE day N "
                        "(day 0 = the corpus's first event — never a calendar date)")
    r.add_argument("--until-day", type=int, default=None, metavar="N",
                   help="analyze only events on or before relative day N; a filtered "
                        "run says so in its audit sentence — subset numbers, not corpus numbers")
    add_format(r)

    d = sub.add_parser("doctor", help="dry-run ingestion: what would be read, what would be "
                                      "dropped, and which analyzers this corpus can feed")
    d.add_argument("path", help="same argument `run` takes for this --adapter")
    d.add_argument("--adapter", required=True, choices=ingest.available())
    d.add_argument("--table", default=None, help="db adapters only: the turns table")
    add_format(d)

    a = sub.add_parser("adapters", help="list the corpus formats that can be read")
    add_format(a)

    z = sub.add_parser("analyzers", help="list the analyzers, their claims and denominators")
    add_format(z)

    df = sub.add_parser("diff", help="compare two `run --format json` files and report the "
                                     "delta for every shared headline number")
    df.add_argument("report_a", help="first run's JSON file (from `corpuslens run --format json`)")
    df.add_argument("report_b", help="second run's JSON file")
    add_format(df)

    args = p.parse_args(argv)
    if args.cmd == "run":
        if args.since_day is not None and args.until_day is not None \
                and args.since_day > args.until_day:
            print(f"error: --since-day {args.since_day} is after --until-day {args.until_day} "
                  f"— that window is empty.", file=sys.stderr)
            return 2
        return run(args.path, args.adapter, args.out, args.table, args.fmt,
                   args.since_day, args.until_day)
    if args.cmd == "doctor":
        return doctor(args.path, args.adapter, args.table, args.fmt)
    if args.cmd == "adapters":
        return adapters(args.fmt)
    if args.cmd == "analyzers":
        return analyzers(args.fmt)
    if args.cmd == "diff":
        return diff_cmd(args.report_a, args.report_b, args.fmt)
    return 2


if __name__ == "__main__":
    sys.exit(main())
