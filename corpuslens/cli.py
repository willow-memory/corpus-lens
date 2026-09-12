"""corpuslens CLI.

    corpuslens run                                      # zero-config: look, report, run
    corpuslens run <path> --adapter claude-code [--format markdown|json] [--share]
    corpuslens doctor <path> --adapter claude-code      # what would be read, and what dropped
    corpuslens adapters                                 # what can be read, and from what
    corpuslens analyzers                                # what gets computed, and out of what
    corpuslens label <path> --adapter claude-code       # label a sample of your own turns
    corpuslens score <path> --adapter claude-code       # classifier precision/recall vs. labels
    corpuslens diff a.json b.json                       # the delta between two --format json runs

Every subcommand runs under the DEFAULT profile: no calendar, no timezone, no
person claims. There is deliberately no CLI flag to grant capabilities — a
grant is an owner-side code change (a Profile constructed in your own script),
not a switch someone can flip in a command line they found in a README.

`label` and `score` are two verbs, not one command with a `--score` flag, on
purpose: `label` is interactive and writes a store; `score` is a read-only
report with its own `--format`. Splitting them keeps each argparse surface
honest about what it actually takes and does, matching this file's existing
one-verb-per-subcommand shape (`run`, `doctor`, `adapters`, `analyzers`)
instead of adding a mode switch to either of those.
`--share` is a MODIFIER on `run`, not a third `--format`: it composes with
either format (`--format json --share` for a machine-readable coarsened
document) rather than forking the renderers. See `corpuslens/share.py` for
what it coarsens and, just as load-bearing, what it does not claim.

`corpuslens run` with NO arguments is zero-config discovery, not a third
shape of the command: omit PATH and `--adapter` TOGETHER (giving only one of
the two is an error, not a partial guess) and it looks in the conventional
locations each "dir" adapter has declared for itself (see
`ingest.register_default_path`), reports what it found there BEFORE reading a
single turn, and then runs the battery on what it found. See `_discover_corpora`
below for the containment rules (never outside `$HOME`, never through a
symlink that leaves it) and `run_discovered` for what happens when several
corpora exist (the largest, by file count, is run — see its docstring for
why). The explicit two-argument form is unchanged by any of this.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

from . import diff as diffmod
from . import ingest, label as labelmod, render
from . import share as share_mod
from . import subject as subjectmod
from .analyze import all_analyzers
from .guard import DEFAULT_PROFILE, Guard, WallError
from . import subject_consent as consentmod

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
        return 0, None  # no filesystem check — the adapter validates the connection
    if not p.exists():
        return 0, f"path does not exist: {path}"
    if src == "dir":
        pat = ingest.pattern_of(adapter)
        if not p.is_dir():
            return 0, (
                f"expected a directory of {pat} session files, got a file: {path}\n"
                f"       point corpuslens at the parent directory, not a single session file."
            )
        return sum(1 for f in p.rglob(pat) if f.is_file()), None
    if p.is_dir():
        return 0, f"adapter '{adapter}' expects a single file, got a directory: {path}"
    return 0, None


def _ingest(path: str, adapter: str, table: str | None):
    """(events, quarantine, drops, n_files) or raises ValueError with a
    ready-to-print message. Shared by `run` and `doctor` so the two can never
    disagree about what a corpus contains. `drops` is an `ingest.drops.DropCounts`
    — see `corpuslens/ingest/__init__.py` for the contract."""
    src = ingest.source_of(adapter)
    n_files, err = _check_path(path, adapter, src)
    if err:
        raise ValueError(err)
    kw = {"table": table} if (table is not None and src in ("file", "dsn")) else {}
    events, quarantine, drops = ingest.get(adapter)(path, **kw)
    return events, quarantine, drops, n_files


def _ingest_for_label(path: str, adapter: str, table: str | None):
    """Like `_ingest`, but through the adapter's `label_text` seam instead of
    its ordinary `ingest()` — a differently-shaped function
    (`ingest.get_label_text`), not the same function under a flag, so `run`/
    `doctor`'s call to `ingest.get(adapter)(...)` never changes shape. Only
    adapters registered via `register_label_text` implement it; callers must
    check `ingest.text_capable_of(adapter)` first."""
    src = ingest.source_of(adapter)
    n_files, err = _check_path(path, adapter, src)
    if err:
        raise ValueError(err)
    kw = {"table": table} if (table is not None and src in ("file", "dsn")) else {}
    lc = ingest.get_label_text(adapter)(path, **kw)
    return lc.events, lc.quarantine, lc.drops, n_files, lc.text_by_ref


def _empty_message(path, adapter, src, n_files, drops, display_path=None) -> str:
    """`display_path` overrides `path` in the text. `run_discovered` passes the
    adapter's declared `~/...` form, because on a DISCOVERED run the user never
    typed the path: echoing the resolved one back would print their username in
    a place they could not have predicted, and the success line for the same
    run already says `~/.claude/projects`. A failure line that says
    `/home/<name>/.claude/projects` for the same corpus is the one place this
    feature was still inconsistent with itself. When the user typed the path,
    `display_path` is None and it is echoed as typed, which is right — it is
    already theirs, and changing it would make the error harder to act on.

    `drops` is an `ingest.drops.DropCounts`; only the aggregate `.total` is
    worth naming in a one-line failure message (a reason breakdown belongs in
    `doctor`, not here)."""
    path = display_path or path
    pat = ingest.pattern_of(adapter)
    if src == "dir" and n_files == 0:
        return f"no {pat} files found under {path}. Wrong directory?"
    if src == "dir":
        return (
            f"{n_files} {pat} file(s) under {path} but none yielded a datable, "
            f"non-empty turn for adapter '{adapter}' (dropped {drops.total}). Wrong adapter?"
        )
    return (
        f"adapter '{adapter}' yielded no datable, non-empty turn from {path} "
        f"(dropped {drops.total}). Wrong table/columns, or an empty corpus?"
    )


def _window(events, since_day, until_day):
    """Filter to a RELATIVE-day window (day 0 = the corpus's first event, never a
    calendar date). Returns (kept, n_excluded, clause|None). A window is a
    subset, and the audit sentence says so — filtered numbers are not corpus
    numbers."""
    if since_day is None and until_day is None:
        return events, 0, None
    lo = since_day if since_day is not None else -(10**9)
    hi = until_day if until_day is not None else 10**9
    kept = [e for e in events if lo <= e.time.day_offset <= hi]
    lo_s = "corpus start" if since_day is None else str(since_day)
    hi_s = "corpus end" if until_day is None else str(until_day)
    return kept, len(events) - len(kept), f"relative-day window {lo_s}..{hi_s}, inclusive"


def _count_files_no_symlinks(root: Path, pattern: str) -> int:
    """Like `p.rglob(pattern)` in `_check_path`, but never follows a symlinked
    directory (`os.walk(..., followlinks=False)` lists one without walking
    into it) and never counts a symlinked file — discovery is looking at
    locations it was not explicitly told to trust, so a link that happens to
    point somewhere else on disk is refused rather than followed, unlike the
    explicit two-argument form (which already trusts whatever the user
    pointed it at, and is unchanged here)."""
    n = 0
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for fn in filenames:
            if not fnmatch.fnmatch(fn, pattern):
                continue
            if (Path(dirpath) / fn).is_symlink():
                continue
            n += 1
    return n


def _discover_corpora() -> list[dict]:
    """For every adapter that has declared a conventional directory
    (`ingest.register_default_path`), check it WITHOUT reading a byte of the
    corpus itself: does it exist under `$HOME`, is it actually a directory,
    and how many files match the adapter's own declared pattern
    (`ingest.pattern_of`) — the same count `_check_path` reports for the
    explicit form. Every declared adapter is reported, found or not, so the
    caller can print the full set of locations that were checked, not just
    the one that gets used.

    Never widens outside `$HOME`: a declared path that resolves somewhere
    else (a symlink, or a future adapter that misdeclares one) is refused,
    not followed — discovery is a guess standing in for a path the user did
    not type, so it earns none of the trust an explicit argument gets. An
    unreadable location (permission denied, a broken parent) is reported in
    `note`, never left to raise.

    Each entry carries BOTH `declared_path` (the adapter's own convention,
    e.g. '~/.claude/projects' — unexpanded, no username) and `resolved_path`
    (an absolute path under `$HOME`, needed to actually open files and to run
    the containment check above). `resolved_path` is for internal use only —
    reading the corpus, and the `> lo <= x <= hi`-style comparison above — and
    must NEVER be shown to the user or stored on anything that leaves this
    process: a resolved path carries the owner's real username. Every caller
    of this function prints or records `declared_path`, never
    `resolved_path`; `guard.AuditRecord.discovered_path` enforces the same
    rule from the other end by refusing to hold a resolved value at all."""
    home = Path.home().resolve()
    found = []
    for name in ingest.discoverable():
        raw = ingest.default_path_of(name)
        pat = ingest.pattern_of(name)
        entry = {
            "adapter": name,
            "declared_path": raw,
            "resolved_path": None,
            "n_files": 0,
            "usable": False,
            "note": None,
        }
        try:
            resolved = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError) as e:
            entry["note"] = f"could not resolve ({e})"
            found.append(entry)
            continue
        entry["resolved_path"] = str(resolved)
        if resolved != home and home not in resolved.parents:
            entry["note"] = "refusing: resolves outside the home directory"
            found.append(entry)
            continue
        try:
            if not resolved.exists():
                entry["note"] = "not present"
                found.append(entry)
                continue
            if not resolved.is_dir():
                entry["note"] = "exists but is not a directory"
                found.append(entry)
                continue
            n = _count_files_no_symlinks(resolved, pat)
        except OSError as e:
            entry["note"] = f"unreadable ({e})"
            found.append(entry)
            continue
        entry["n_files"] = n
        entry["usable"] = n > 0
        entry["note"] = f"{n} {pat} file(s) found" if n else f"present, but no {pat} files under it"
        found.append(entry)
    return found


def run_discovered(
    out: str | None, fmt: str, since_day: int | None, until_day: int | None, share: bool
) -> int:
    """`corpuslens run` with no PATH and no `--adapter`: look in every
    adapter's declared conventional location, print what was found at each
    one BEFORE reading anything, then run the battery on what was found.

    THE MULTIPLE-CORPORA DECISION. When more than one location is usable,
    this runs the LARGEST by file count and says so, rather than running each
    in turn or refusing and asking. Reasoning: `run` renders ONE report, and
    multiplexing it into several would either pick one anyway (a report needs
    one audit sentence, one set of findings) or dump every corpus's numbers
    into one call in a shape nothing here renders; asking is right for an
    interactive prompt but this is a first run that may be piped or scripted,
    and a question nobody can answer non-interactively is worse than a
    reasonable default that says what it did and how to override it. Largest
    is the one most likely to give a first-time reader real numbers instead
    of a `n < 30` disclaimer. Any of the three options in IDEAS.md's own
    framing is defensible; this is the one that keeps `run` a single-report
    command and degrades gracefully to a stated guess instead of a stall."""
    found = _discover_corpora()
    lines = ["No path or --adapter given — looking in conventional locations:", ""]
    for e in found:
        lines.append(f"  - {e['adapter']}: {e['declared_path']} — {e['note']}")
    usable = [e for e in found if e["usable"]]
    if not usable:
        lines += [
            "",
            "No corpus found in any conventional location. Point corpuslens at one explicitly:",
            "",
            "  corpuslens run <path> --adapter <adapter>",
            "",
            "Run `corpuslens adapters` to see what each adapter expects.",
        ]
        print("\n".join(lines), file=sys.stderr)
        return 1
    chosen = max(usable, key=lambda e: e["n_files"])
    lines.append("")
    # DISPLAY the DECLARED form only (e.g. '~/.claude/projects'), never
    # `resolved_path` — the resolved absolute path is $HOME plus that same
    # constant, and $HOME is exactly where the owner's real username lives.
    # `resolved_path` is used below ONLY to hand `run()` a real filesystem
    # location to read from, never to print.
    if len(usable) > 1:
        others = ", ".join(
            f"{e['adapter']} ({e['n_files']} files)" for e in usable if e is not chosen
        )
        lines.append(
            f"Found corpora in {len(usable)} locations ({others} too); running the "
            f"LARGEST by file count: '{chosen['adapter']}' at "
            f"{chosen['declared_path']} ({chosen['n_files']} files). Run corpuslens "
            f"with an explicit path and --adapter to analyze a different one instead."
        )
    else:
        lines.append(
            f"Using '{chosen['adapter']}' at {chosen['declared_path']} ({chosen['n_files']} files)."
        )
    print("\n".join(lines))
    print()
    return run(
        chosen["resolved_path"],
        chosen["adapter"],
        out,
        None,
        fmt,
        since_day,
        until_day,
        share,
        discovered_path=chosen["declared_path"],
    )


def run(
    path: str,
    adapter: str,
    out: str | None,
    table: str | None = None,
    fmt: str = "markdown",
    since_day: int | None = None,
    until_day: int | None = None,
    share: bool = False,
    discovered_path: str | None = None,
    subject: str | None = None,
    consent_store: str | None = None,
) -> int:
    """`path`/`adapter` are always the REAL location to read from, typed by
    the user or resolved by `run_discovered` — that never changes here.

    `discovered_path`, when not None, is a SEPARATE, DISPLAY-ONLY string:
    the adapter's declared conventional form (e.g. '~/.claude/projects', from
    `ingest.default_path_of`) passed by `run_discovered` so the audit record
    can say the corpus was found rather than typed. It is never derived from
    `path` here and never resolved — `guard.AuditRecord.__setattr__` refuses
    a resolved value outright, because a resolved path under $HOME carries
    the owner's real username into the same sentence that claims nothing
    identifying left the wall (see NOTES-zeroconf.md). Putting it in the
    audit record puts it in the SAME sentence that already names the
    adapter, so a reader of the report alone (not just this run's terminal
    output) can see what was read.

    `subject`/`consent_store` name a subject who is NOT the owner (see
    corpuslens/subject_consent.py). Both or neither. When given, the subject's
    `process_analysis` grant is verified BEFORE the adapter opens anything,
    fail-closed; after a report clears the egress scan, one counts-only row is
    appended to that subject's disclosure chain. Without them nothing here
    changes: this is the owner's own corpus, the case every other line of
    this function was written for."""
    src = ingest.source_of(adapter)
    rc = _subject_gate(subject, consent_store)
    if rc:
        return rc
    try:
        events, quarantine, drops, n_files = _ingest(path, adapter, table)
    except (
        FileNotFoundError,
        IsADirectoryError,
        NotADirectoryError,
        ValueError,
        RuntimeError,
    ) as e:
        # the ingest error text can quote the resolved path; on a discovered run
        # the user never typed it, so swap it for the declared form.
        msg = (
            str(e).replace(str(Path(path).expanduser().resolve()), discovered_path)
            if discovered_path
            else str(e)
        )
        print(f"error: {msg}", file=sys.stderr)
        return 2

    if not events:
        print(
            f"error: {_empty_message(path, adapter, src, n_files, drops, discovered_path)}",
            file=sys.stderr,
        )
        return 1

    events, n_filtered, clause = _window(events, since_day, until_day)
    if not events:
        print(
            f"error: the --since-day/--until-day window ({clause}) excluded every event "
            f"({n_filtered} dropped by the window). Widen it.",
            file=sys.stderr,
        )
        return 1

    guard = Guard(quarantine, DEFAULT_PROFILE)
    guard.audit.n_events = len(events)
    guard.audit.n_dropped = drops.total
    guard.audit.n_dropped_structural = drops.structural
    guard.audit.n_dropped_malformed = drops.malformed
    guard.audit.dropped_by_reason = drops.as_dict()
    guard.audit.adapter = adapter
    if discovered_path:
        guard.audit.discovered_path = discovered_path
    if subject:
        guard.audit.subject_consent = consentmod.SCOPE  # the scope, never the id
    if clause:
        guard.audit.filters.append(clause)
        guard.audit.n_filtered = n_filtered

    results = {}
    unmeasurable = ingest.unmeasurable_of(adapter)
    for a in all_analyzers():
        if a.name in unmeasurable:
            # The adapter said this corpus cannot mean this number. Refuse
            # by name, in the same list the Guard's own refusals go in, so
            # the audit sentence carries it — see ingest.register_unmeasurable.
            guard.audit.analyzers_refused.append(
                f"{a.name} (adapter {adapter}: {unmeasurable[a.name]})"
            )
            continue
        if not guard.admit(a):
            continue
        results[a.name] = {
            "denominator": a.denominator,
            "analyzer_version": a.version,
            "grading_question": a.grading_question,
            **a.run(events),
        }
        guard.audit.analyzers_run.append(a.name)
    # DERIVED, never a flag: this run's own authorship_mix result (when that
    # analyzer is registered) is the only input — see corpuslens/subject.py.
    # Always set, even when nothing ran to inform it, so the audit sentence
    # always says what this run believes about who the operator role is,
    # rather than only saying so on the runs where it changes the answer.
    guard.audit.subject, guard.audit.subject_reason = subjectmod.infer_subject(results)
    audit = guard.audit
    if share:
        # Coarsening happens on the already-computed numbers, never on the
        # events: share mode changes what leaves the report, not what the
        # analyzers see or compute. See corpuslens/share.py for the rule
        # ("a field survives only if it is explicitly recognised") and for
        # what this output does NOT claim to be (not anonymous, not
        # de-identified, not proven safe to publish).
        #
        # The audit record is coarsened too, into a SEPARATE record (never
        # mutating guard.audit itself) — its exact n_events/n_dropped/
        # n_filtered are the same class of quantity `n` banding exists to
        # blur for every analyzer, and the sentence would otherwise say
        # "This run read 21 events" even while every rate above it reads
        # "n = 30-100". A prior version of this feature missed exactly this.
        results = share_mod.coarsen(results)
        audit = share_mod.coarsen_audit(audit)
    try:
        if share:
            # Second, distinct check `DESIGN-guard-extraction.md` (2a) calls
            # for: a schema/shape assertion on the COARSENED payload itself,
            # before it is rendered to text — `scan_egress` below only ever
            # sees rendered text and cannot tell a banded n from an exact
            # one. Runs BEFORE render()/scan_egress() because it needs the
            # structured dict, not text; see guard.Guard.scan_share_shape's
            # docstring for why this is not a duplicate of scan_egress.
            guard.scan_share_shape(results, audit.as_dict())
        report = render.render(fmt, results, audit, share=share)
        report = guard.scan_egress(report)  # fail-closed backstop at the output door
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
    if subject:
        # Only now: a refused or unwritten report leaves no "analysis ran" row.
        _disclose(
            subject,
            consent_store,
            consentmod.ACTION_RUN,
            adapter,
            guard.audit.n_events,
            guard.audit.n_dropped,
        )
    return 0


def _subject_gate(subject: str | None, consent_store: str | None) -> int:
    """0 to proceed; a non-zero exit code (already printed) otherwise. Runs
    BEFORE ingest, so a subject whose grant cannot be verified has their
    corpus left unopened. Both flags or neither — half a consent object is
    refused, not guessed at, the same rule `run` applies to PATH/--adapter."""
    if subject is None and consent_store is None:
        return 0
    if subject is None or consent_store is None:
        print(
            "error: --subject and --consent-store go together: a subject who is not the "
            "owner needs a store holding their grant, and a store needs a subject to look "
            "up. Give both, or neither (the owner's own corpus).",
            file=sys.stderr,
        )
        return 2
    try:
        consentmod.require_grant(consent_store, subject)
    except consentmod.SubjectRefused as e:
        print(f"error: subject consent refused: {e}", file=sys.stderr)
        return 4
    return 0


def _disclose(
    subject: str,
    consent_store: str | None,
    action: str,
    adapter: str,
    n_events: int,
    n_dropped: int,
) -> None:
    """Append the counts-only disclosure row; a failure to write it is loud
    (stderr) but never retracts a report already emitted."""
    try:
        consentmod.disclose(
            consent_store or "",
            subject,
            action,
            adapter=adapter,
            n_events=n_events,
            n_dropped=n_dropped,
        )
    except consentmod.core.SubjectConsentError as e:
        print(
            f"warning: the disclosure row could not be appended ({e.__class__.__name__}); "
            f"the subject's record does not show this run.",
            file=sys.stderr,
        )


def _diagnose(events, quarantine, drops, adapter, src, n_files, path) -> dict:
    """Counts only — never content, never the anchor itself (only whether one
    was quarantined). Split out from `doctor` so the numbers and their
    rendering can be tested apart.

    `drops` is an `ingest.drops.DropCounts` (BUGS.md, Open #1, Fixed): the old
    combined `drop_pct` conflated "not a turn by design" (tool traffic,
    thinking, attachments, harness bookkeeping — normal, no reason to distrust
    anything) with "should have been a turn and failed" (an unparseable line,
    a missing timestamp, an unrecognised role, an empty turn — the number a
    reader should actually judge a corpus by). `drop_pct` below stays as the
    combined figure for continuity; the warning fires on `malformed_drop_pct`
    only, computed over CANDIDATE turns (kept + malformed) so a corpus that is
    mostly tool traffic by design — the case that made this warning misfire on
    a modern agentic corpus — no longer trips it."""
    total = len(events) + drops.total
    op = [e for e in events if e.author_class == "operator"]
    machine = [e for e in events if e.author_class == "machine"]
    threads = {e.thread_id for e in events}
    days = {e.time.day_offset for e in events}
    with_delta = sum(1 for e in events if e.time.delta_prev_s is not None)
    candidate_turns = len(events) + drops.malformed
    diag = {
        "adapter": adapter,
        "source_kind": src,
        "source_files_seen": n_files if src == "dir" else None,
        "source_file_pattern": ingest.pattern_of(adapter) if src == "dir" else None,
        "records_read": total,
        "events_kept": len(events),
        "events_dropped": drops.total,
        "events_dropped_structural": drops.structural,
        "events_dropped_malformed": drops.malformed,
        "drop_pct": round(100 * drops.total / total, 1) if total else 0.0,
        "malformed_drop_pct": (
            round(100 * drops.malformed / candidate_turns, 1) if candidate_turns else 0.0
        ),
        "dropped_by_reason": drops.as_dict(),
        "operator_turns": len(op),
        "machine_turns": len(machine),
        "threads": len(threads),
        "relative_day_span": (max(days) - min(days) + 1) if days else 0,
        "turns_with_tempo_delta": with_delta,
        "anchor_quarantined": bool(quarantine.base_date_iso),
    }
    notes = []
    if not events:
        notes.append(_empty_message(path, adapter, src, n_files, drops))
    if events and not machine:
        notes.append("no machine turns: `clarification_pull` cannot be computed on this corpus.")
    if events and not with_delta:
        notes.append(
            "no within-day tempo deltas: `tempo` cannot be computed on this corpus "
            "(a store that does not clock prompts, or one turn per thread per day)."
        )
    if diag["malformed_drop_pct"] >= 50.0:
        notes.append(
            f"{diag['malformed_drop_pct']}% of the records that should have been a "
            f"turn failed to become one (unparseable lines, missing timestamps, "
            f"unrecognised roles, empty turns) — check the adapter (and --table) "
            f"before trusting any rate computed from the rest. This does NOT count "
            f"the {diag['events_dropped_structural']} record(s) dropped by design "
            f"(tool traffic, thinking, attachments, harness bookkeeping) — those are "
            f"normal and not part of this warning."
        )
    if not quarantine.base_date_iso and events:
        notes.append("no calendar anchor was quarantined for this corpus.")
    for name, why in sorted(ingest.unmeasurable_of(adapter).items()):
        notes.append(
            f"`{name}` is declared unmeasurable by the {adapter!r} adapter and will "
            f"be refused by `run`: {why}."
        )
    diag["notes"] = notes
    diag["reminder"] = (
        "diagnostics only — no analyzer ran, no rate was computed, and the "
        "calendar anchor stayed quarantined."
    )
    return diag


def _render_doctor(diag: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(diag, indent=2, default=str)
    lines = ["# corpuslens doctor", ""]
    for k, v in diag.items():
        if k in ("notes", "reminder", "dropped_by_reason") or v is None:
            continue
        lines.append(f"- **{k}**: {v}")
    if diag.get("dropped_by_reason"):
        lines += ["", "## dropped_by_reason"] + [
            f"- **{reason}**: {n}" for reason, n in sorted(diag["dropped_by_reason"].items())
        ]
    if diag["notes"]:
        lines += ["", "## notes"] + [f"- {n}" for n in diag["notes"]]
    lines += ["", f"*{diag['reminder']}*"]
    return "\n".join(lines)


def doctor(
    path: str,
    adapter: str,
    table: str | None = None,
    fmt: str = "markdown",
    subject: str | None = None,
    consent_store: str | None = None,
) -> int:
    """A dry run of ingestion only: what this adapter can see in this corpus,
    how much it had to drop, and which analyzers that corpus can actually feed
    — before committing to a report. Runs no analyzer and emits no rates.

    Same wall as `run`: relative days only, counts rather than content, and the
    output passes the same fail-closed egress scan — a diagnostic is an output
    door too, and must not be the quieter way out. Same consent gate as `run`,
    too: a dry run still opens the subject's files, so a non-owner subject
    needs the same verified grant, and gets the same disclosure row.
    """
    src = ingest.source_of(adapter)
    rc = _subject_gate(subject, consent_store)
    if rc:
        return rc
    try:
        events, quarantine, drops, n_files = _ingest(path, adapter, table)
    except (
        FileNotFoundError,
        IsADirectoryError,
        NotADirectoryError,
        ValueError,
        RuntimeError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    diag = _diagnose(events, quarantine, drops, adapter, src, n_files, path)
    if subject:
        diag["subject_consent"] = consentmod.SCOPE  # the scope verified, never the id
    text = _render_doctor(diag, fmt)
    try:
        text = Guard(quarantine, DEFAULT_PROFILE).scan_egress(text)
    except WallError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    print(text)
    if subject:
        _disclose(
            subject, consent_store, consentmod.ACTION_DOCTOR, adapter, len(events), drops.total
        )
    return 0 if events else 1


def consent_cmd(action: str, subject: str, store: str, by: str | None, fmt: str) -> int:
    """`corpuslens consent grant|revoke|status SUBJECT --store DIR [--by NAME]`.
    The operator seat: grants and revocations are made here, by a named
    grantor, on a hash-chained record, and never from `run`. The subject id
    is echoed back only on this terminal, never into a report."""
    try:
        if action == "grant":
            if not by:
                print(
                    "error: --by NAME is required: a grant with no grantor is not a grant.",
                    file=sys.stderr,
                )
                return 2
            head = consentmod.grant(store, subject, by)
            print(f"granted '{consentmod.SCOPE}' (chain head {head[:16]})")
            return 0
        if action == "revoke":
            if not by:
                print(
                    "error: --by NAME is required: a revocation is signed like a grant.",
                    file=sys.stderr,
                )
                return 2
            head = consentmod.revoke(store, subject, by)
            print(f"revoked '{consentmod.SCOPE}' (chain head {head[:16]})")
            return 0
    except consentmod.core.SubjectConsentError as e:
        print(f"error: {e.__class__.__name__}: {e}", file=sys.stderr)
        return 4
    st = consentmod.status(store, subject)
    if fmt == "json":
        print(json.dumps(st, indent=2))
        return 0
    print("# corpuslens consent status")
    print()
    print(f"- **store present**: {st['store_present']}")
    for scope, ok in st["scopes"].items():
        print(f"- **{scope}**: {'granted' if ok else 'not granted'}")
    print(f"- **disclosure chain**: {st['disclosure_chain']} ({len(st['disclosures'])} row(s))")
    for row in st["disclosures"]:
        print(f"  - {row['action']}: {row['detail']}")
    return 0


def adapters(fmt: str = "markdown") -> int:
    rows = [
        {"adapter": name, "argument": ingest.source_of(name), "expects": _expects(name)}
        for name in ingest.available()
    ]
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
    rows = [
        {
            "analyzer": a.name,
            "claims": list(a.claims),
            "denominator": a.denominator,
            "version": a.version,
            "grading_question": a.grading_question,
        }
        for a in all_analyzers()
    ]
    if fmt == "json":
        print(json.dumps(rows, indent=2))
    else:
        print("# corpuslens analyzers")
        print()
        for r in rows:
            print(
                f"- **{r['analyzer']}** (v{r['version']}) — claims {', '.join(r['claims'])}; "
                f"out of {r['denominator']}"
            )
            print(f"  - GRADING.md: {r['grading_question']}")
        print()
        print(
            "*Every rate names its denominator, and every claim type is on the process-only "
            "allowlist in `model.py` — a person-shaped claim has no representation here. The "
            "version is the analyzer's SEMANTICS (classifiers/thresholds), not the JSON document "
            "shape — see `corpuslens.analyze.Analyzer` — and `corpuslens diff` withholds the "
            "delta for any analyzer whose version disagrees between the two runs. GRADING.md "
            "questions 5-8 (honesty machinery) and 9-10 (fingerprinting, continuity) are not "
            "corpus-measurable and have no analyzer here at all — see GRADING.md itself.*"
        )
    return 0


def _ask_yes_no(question: str):
    """Prompt once, re-asking on garbage input. Returns True/False, or None to
    mean 'stop here' — either the operator typed q/quit, or stdin ran out
    (EOFError) mid-session, which is treated as a graceful early stop rather
    than a crash so a partially piped or truncated session still saves what it
    has. The CLI checks `sys.stdin.isatty()` before ever calling this, so EOF
    here is a defensive backstop, not the primary non-tty guard."""
    while True:
        try:
            raw = input(f"{question} [y/n/q] ").strip().lower()
        except EOFError:
            return None
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        if raw in ("q", "quit"):
            return None
        print("please answer y, n, or q.")


def label(
    path: str, adapter: str, sample_size: int, store_path: str, table: str | None = None
) -> int:
    """Sample eligible turns under a fixed seed, show each one's text in the
    terminal, and ask one yes/no per classifier that applies to it, plus (when
    `corpuslens.authorship` is installed) the one authorship question for
    every eligible turn. Writes only {source_ref, classifier, label} per
    regex answer and {source_ref, label} per authorship answer, tagged with
    their own version each — never content (see label.py's module docstring
    for the exact rule this enforces).

    Authorship is folded into the SAME sample and the SAME per-turn prompt
    sequence as the regex questions, rather than a separate `label` run: the
    labeller is already looking at this turn to answer "did you author code
    here", and "did a person type this at all" is one more question about
    the same turn, not a reason to make them label the corpus twice. If the
    authorship module is not installed, that question is silently skipped
    (with a one-line note) and the regex questions proceed exactly as
    before — this file must keep grading the four regex classifiers whether
    or not the sibling classifier has shipped yet.
    """
    if not ingest.text_capable_of(adapter):
        print(
            f"error: 'label' needs to show you your own turn text, and the {adapter!r} "
            f"adapter does not support that yet (only claude-code does) — refusing rather "
            f"than guessing at a text format nobody has implemented or tested for it.",
            file=sys.stderr,
        )
        return 2
    try:
        events, quarantine, drops, n_files, text_by_ref = _ingest_for_label(path, adapter, table)
    except (
        FileNotFoundError,
        IsADirectoryError,
        NotADirectoryError,
        ValueError,
        RuntimeError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not events:
        print(
            f"error: {_empty_message(path, adapter, ingest.source_of(adapter), n_files, drops)}",
            file=sys.stderr,
        )
        return 1

    try:
        store = labelmod.load_store(store_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error: could not read --store {store_path}: {e}", file=sys.stderr)
        return 2
    version_err = labelmod.check_version(store)
    if version_err:
        print(f"error: {version_err}", file=sys.stderr)
        return 2

    authorship_mod = None
    try:
        authorship_mod = labelmod.authorship_contract()
    except labelmod.AuthorshipUnavailable:
        pass
    if authorship_mod is not None:
        authorship_version_err = labelmod.check_authorship_version(
            store, authorship_mod.AUTHORSHIP_VERSION
        )
        if authorship_version_err:
            print(f"error: {authorship_version_err}", file=sys.stderr)
            return 2

    sample = labelmod.sample_events(events, sample_size)
    if not sample:
        print(
            "error: no eligible turns to sample in this corpus (operator prompts or machine "
            "responses with >=12 characters).",
            file=sys.stderr,
        )
        return 1

    labelled = labelmod.already_labelled(store)
    authorship_labelled = labelmod.already_labelled_authorship(store)
    pending = []
    for e in sample:
        classifiers = [
            c for c in labelmod.classifiers_for(e.author_class) if (e.source_ref, c) not in labelled
        ]
        needs_authorship = authorship_mod is not None and e.source_ref not in authorship_labelled
        if classifiers or needs_authorship:
            pending.append((e, classifiers, needs_authorship))
    if not pending:
        print(
            f"nothing new to label: all {len(sample)} sampled turn(s) already have a label "
            f"for every classifier (and authorship judgment, if applicable) that applies to "
            f"them, in {store_path}."
        )
        return 0

    if not sys.stdin.isatty():
        print(
            "error: `corpuslens label` is interactive — it reads y/n answers from a terminal, "
            "and stdin here is not one (a piped input, or a CI run). Run it directly in a "
            "terminal instead of redirecting stdin.",
            file=sys.stderr,
        )
        return 2

    print(
        f"{len(pending)} of {len(sample)} sampled turn(s) still need a label "
        f"(sample fixed by seed — the same corpus and --sample-size sample the same turns)."
    )
    print("Answer y or n for each question, or q to stop and save what you have so far.")
    if authorship_mod is None:
        print(
            "(the authorship classifier is not installed in this build — skipping its "
            "question; the classifier questions below are unaffected.)"
        )
    print()
    asked = 0
    for e, classifiers, needs_authorship in pending:
        text = text_by_ref.get(e.source_ref)
        if text is None:
            continue
        print("-" * 70)
        print(f"[{e.author_class.value} turn]")
        print(text)
        print("-" * 70)
        stopped = False
        for c in classifiers:
            answer = _ask_yes_no(labelmod.QUESTIONS[c])
            if answer is None:
                stopped = True
                break
            labelmod.add_label(store, e.source_ref, c, answer)
            asked += 1
        if not stopped and needs_authorship:
            answer = _ask_yes_no(labelmod.AUTHORSHIP_QUESTION)
            if answer is None:
                stopped = True
            else:
                label_value = authorship_mod.HUMAN if answer else authorship_mod.AGENT
                labelmod.add_authorship_label(
                    store, e.source_ref, label_value, authorship_mod.AUTHORSHIP_VERSION
                )
                asked += 1
        print()
        if stopped:
            break
    labelmod.save_store(store_path, store)
    print(f"{asked} label(s) recorded to {store_path}.")
    return 0


def _render_authorship(result: dict) -> list:
    """Render `score_authorship`'s result. Deliberately not a confusion-matrix
    dump: one coverage line (how often the classifier even answered) up
    front, then precision/recall per class — the same shape as the regex
    classifiers above — with each class's `fn` broken into "predicted the
    other class" versus "declined (unknown)" so those two failure modes
    never collapse into a single indistinguishable number."""
    lines = [
        "## authorship",
        "",
        "*Three-valued: human / agent / unknown. UNKNOWN is the classifier declining "
        "to answer, not a wrong guess — a classifier that answers unknown on every turn "
        'shows 0% recall below for BOTH classes and "not computable" precision, never a '
        "flattering 100%. Read recall together with the decline rate below it, not alone.*",
        "",
    ]
    n = result["n"]
    lines.append(f"n = {n} authorship-labelled turn(s) found in this corpus.")
    if result.get("missing"):
        lines.append(
            f"*{result['missing']} authorship-labelled turn(s) were not found in this "
            f"run of the corpus (counted, not silently dropped).*"
        )
    if n == 0:
        lines.append(f"*{result['unknown_note']}*")
        lines.append("")
        return lines
    if 0 < n < render.SMALL_N:
        lines.append(f"*Small sample (n = {n}): read the direction, not the decimal.*")
    lines.append(
        f"- **declined (unknown)**: {result['unknown_pct']}% of turns "
        f"({result['unknown_n']} of {n}) — the classifier did not answer at all"
    )
    lines.append("")
    for name in ("human", "agent"):
        r = result[name]
        lines.append(f"### {name}")
        lines.append("")
        if r["precision_pct"] is not None:
            lines.append(
                f"- **precision**: {r['precision_pct']}% — out of "
                f"{r['precision_denominator']} (tp={r['tp']}, fp={r['fp']})"
            )
        else:
            lines.append(f"- **precision**: {r['precision_note']}")
        if r["recall_pct"] is not None:
            lines.append(
                f"- **recall**: {r['recall_pct']}% — out of "
                f"{r['recall_denominator']} (tp={r['tp']}, fn={r['fn']})"
            )
        else:
            lines.append(f"- **recall**: {r['recall_note']}")
        lines.append(
            f"  - of {r['fn']} missed {name} turn(s): {r['fn_wrong']} the classifier "
            f"answered wrong (the other class), {r['fn_declined']} it declined "
            f"(unknown) — said-unknown and said-wrong are counted separately on purpose."
        )
        lines.append("")
    return lines


def _render_score(result: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(result, indent=2)
    lines = [
        "# corpuslens score",
        "",
        f"*Precision and recall of the regex classifiers against "
        f"{result['total_labels']} human label(s) — your own judgment on your own turns, "
        f"never a model's. Named denominators below; this covers only the classifiers and "
        f"the corpus this label store actually has labels for.*",
        "",
    ]
    if result["missing"]:
        lines.append(
            f"*{result['missing']} labelled turn(s) were not found in this run of the "
            f"corpus (counted, not silently dropped) — the corpus may have changed "
            f"since labelling.*"
        )
        lines.append("")
    if not result["classifiers"] and not result.get("authorship"):
        lines.append("No labelled turn in the store matched a turn in this corpus.")
        return "\n".join(lines)
    for name, r in result["classifiers"].items():
        lines.append(f"## {name}")
        lines.append("")
        n = r["n"]
        lines.append(f"n = {n} labelled turn(s) for this classifier.")
        if 0 < n < render.SMALL_N:
            lines.append(f"*Small sample (n = {n}): read the direction, not the decimal.*")
        if r["precision_pct"] is not None:
            lines.append(
                f"- **precision**: {r['precision_pct']}% — out of "
                f"{r['precision_denominator']} (tp={r['tp']}, fp={r['fp']})"
            )
        else:
            lines.append(f"- **precision**: {r['precision_note']}")
        if r["recall_pct"] is not None:
            lines.append(
                f"- **recall**: {r['recall_pct']}% — out of "
                f"{r['recall_denominator']} (tp={r['tp']}, fn={r['fn']})"
            )
        else:
            lines.append(f"- **recall**: {r['recall_note']}")
        lines.append("")
    if result.get("authorship"):
        lines.extend(_render_authorship(result["authorship"]))
    return "\n".join(lines)


def score(
    path: str, adapter: str, table: str | None, store_path: str, fmt: str = "markdown"
) -> int:
    """Re-run the classifiers over `path` and grade them against the labels in
    `store_path`: precision, recall and n per classifier, named denominators
    throughout, plus (when the store has any and `corpuslens.authorship` is
    installed) per-class precision/recall for the three-valued authorship
    judgment. Refuses (does not silently compare) if the store was graded
    against a different classifier-set version, or a different authorship
    version, than the one installed — the two are checked independently,
    since they move on independent schedules (see label.py)."""
    try:
        events, quarantine, drops, n_files = _ingest(path, adapter, table)
    except (
        FileNotFoundError,
        IsADirectoryError,
        NotADirectoryError,
        ValueError,
        RuntimeError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not Path(store_path).exists():
        print(
            f"error: no label store at {store_path} — run `corpuslens label` first.",
            file=sys.stderr,
        )
        return 1
    try:
        store = labelmod.load_store(store_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error: could not read --store {store_path}: {e}", file=sys.stderr)
        return 2
    if not store["labels"] and not store.get("authorship_labels"):
        print(
            f"error: {store_path} has no labels yet — run `corpuslens label` first.",
            file=sys.stderr,
        )
        return 1
    version_err = labelmod.check_version(store)
    if version_err:
        print(f"error: {version_err}", file=sys.stderr)
        return 2

    authorship_mod = None
    if store.get("authorship_labels"):
        try:
            authorship_mod = labelmod.authorship_contract()
        except labelmod.AuthorshipUnavailable as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        authorship_version_err = labelmod.check_authorship_version(
            store, authorship_mod.AUTHORSHIP_VERSION
        )
        if authorship_version_err:
            print(f"error: {authorship_version_err}", file=sys.stderr)
            return 2

    result = labelmod.score(events, store)
    result["authorship"] = labelmod.score_authorship(events, store) if authorship_mod else None
    text = _render_score(result, fmt)
    try:
        text = Guard(quarantine, DEFAULT_PROFILE).scan_egress(text)
    except WallError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    print(text)
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
        parser.add_argument(
            "--format",
            default="markdown",
            choices=render.available(),
            dest="fmt",
            help="output format (default: markdown)",
        )

    r = sub.add_parser(
        "run",
        help="run the process battery on a corpus "
        "(a directory, a SQLite .db, or a Postgres DSN) -- "
        "or, with no arguments, discover one",
    )
    r.add_argument(
        "path",
        nargs="?",
        default=None,
        help="directory of *.jsonl, a SQLite .db file, or a "
        "Postgres connection string, per --adapter. Omit this AND --adapter "
        "together to auto-discover a corpus in conventional locations "
        "(~/.claude/projects, ~/.cursor/chats, ~/.gemini/tmp).",
    )
    r.add_argument(
        "--adapter",
        default=None,
        choices=ingest.available(),
        help="required unless PATH is also omitted for auto-discovery",
    )
    r.add_argument("--out", default=None)
    r.add_argument(
        "--table",
        default=None,
        help="db adapters only: the turns table (schema.table ok); "
        "auto-detected when the db has one obvious candidate",
    )
    r.add_argument(
        "--since-day",
        type=int,
        default=None,
        metavar="N",
        help="analyze only events on or after RELATIVE day N "
        "(day 0 = the corpus's first event — never a calendar date)",
    )
    r.add_argument(
        "--until-day",
        type=int,
        default=None,
        metavar="N",
        help="analyze only events on or before relative day N; a filtered "
        "run says so in its audit sentence — subset numbers, not corpus numbers",
    )
    r.add_argument(
        "--subject",
        default=None,
        metavar="ID",
        help="this corpus is about someone who is NOT you: an opaque local id whose "
        "'process_analysis' consent grant must verify in --consent-store before "
        "anything is read (fail-closed). Omit for your own corpus. See "
        "corpuslens/subject_consent.py.",
    )
    r.add_argument(
        "--consent-store",
        default=None,
        metavar="DIR",
        help="the consent store directory (`corpuslens consent grant ...`); "
        "required with --subject",
    )
    r.add_argument(
        "--share",
        action="store_true",
        help="coarsen the report for sharing off this machine: headline rates "
        "only, n rounded to a wide band, no tempo quantiles/thread counts/day "
        "spans/concurrency figures. Composes with --format (e.g. --format json "
        "--share). NOT a claim that the result is anonymous or safe to publish "
        "— see corpuslens/share.py.",
    )
    add_format(r)

    d = sub.add_parser(
        "doctor",
        help="dry-run ingestion: what would be read, what would be "
        "dropped, and which analyzers this corpus can feed",
    )
    d.add_argument("path", help="same argument `run` takes for this --adapter")
    d.add_argument("--adapter", required=True, choices=ingest.available())
    d.add_argument("--table", default=None, help="db adapters only: the turns table")
    d.add_argument("--subject", default=None, metavar="ID", help="as for `run`")
    d.add_argument("--consent-store", default=None, metavar="DIR", help="as for `run`")
    add_format(d)

    a = sub.add_parser("adapters", help="list the corpus formats that can be read")
    add_format(a)

    z = sub.add_parser("analyzers", help="list the analyzers, their claims and denominators")
    add_format(z)

    lb = sub.add_parser(
        "label",
        help="interactively label a sample of your own turns, to "
        "measure the classifiers' own precision/recall",
    )
    lb.add_argument("path", help="same argument `run` takes for this --adapter")
    lb.add_argument("--adapter", required=True, choices=ingest.available())
    lb.add_argument("--table", default=None, help="db adapters only: the turns table")
    lb.add_argument(
        "--sample-size",
        type=int,
        default=labelmod.DEFAULT_SAMPLE_SIZE,
        metavar="N",
        help=f"how many eligible turns to sample (default: "
        f"{labelmod.DEFAULT_SAMPLE_SIZE}). This is a CONVENTION, like the "
        f"renderer's small-sample threshold — not a power analysis. corpuslens "
        f"does not compute how large a sample would need to be for a given "
        f"confidence (see IDEAS.md, 'A local labelling mode').",
    )
    lb.add_argument(
        "--store",
        default="corpuslens-labels.json",
        dest="store_path",
        help="JSON file to read/write labels (default: ./corpuslens-labels.json). "
        "Holds only label values, each turn's opaque hash, and the classifier "
        "version graded — never content, a filename, or a timestamp.",
    )

    sc = sub.add_parser(
        "score",
        help="precision/recall/n per classifier, from a label store `corpuslens label` made",
    )
    sc.add_argument(
        "path", help="the same corpus you labelled — re-ingested to re-run the classifiers over it"
    )
    sc.add_argument("--adapter", required=True, choices=ingest.available())
    sc.add_argument("--table", default=None, help="db adapters only: the turns table")
    sc.add_argument(
        "--store",
        default="corpuslens-labels.json",
        dest="store_path",
        help="the label store to grade against (default: ./corpuslens-labels.json)",
    )
    add_format(sc)
    df = sub.add_parser(
        "diff",
        help="compare two `run --format json` files and report the "
        "delta for every shared headline number",
    )
    df.add_argument("report_a", help="first run's JSON file (from `corpuslens run --format json`)")
    df.add_argument("report_b", help="second run's JSON file")
    add_format(df)

    cs = sub.add_parser(
        "consent",
        help="the operator seat for a subject who is not you: "
        "grant, revoke, or show a subject's consent record",
    )
    cs.add_argument("action", choices=["grant", "revoke", "status"])
    cs.add_argument("subject", help="the subject's opaque local id")
    cs.add_argument("--store", required=True, metavar="DIR", help="the consent store directory")
    cs.add_argument(
        "--by",
        default=None,
        metavar="NAME",
        help="who is granting/revoking — recorded on the chain (grant/revoke)",
    )
    add_format(cs)

    args = p.parse_args(argv)
    if args.cmd == "run":
        if (
            args.since_day is not None
            and args.until_day is not None
            and args.since_day > args.until_day
        ):
            print(
                f"error: --since-day {args.since_day} is after --until-day {args.until_day} "
                f"— that window is empty.",
                file=sys.stderr,
            )
            return 2
        if args.path is None and args.adapter is None:
            if args.subject is not None or args.consent_store is not None:
                print(
                    "error: --subject cannot be combined with auto-discovery: a corpus that "
                    "is someone else's is named, never guessed at.",
                    file=sys.stderr,
                )
                return 2
            return run_discovered(args.out, args.fmt, args.since_day, args.until_day, args.share)
        if args.path is None or args.adapter is None:
            print(
                "error: give both PATH and --adapter, or neither (to auto-discover a corpus "
                "in conventional locations) — see `corpuslens run --help`.",
                file=sys.stderr,
            )
            return 2
        return run(
            args.path,
            args.adapter,
            args.out,
            args.table,
            args.fmt,
            args.since_day,
            args.until_day,
            args.share,
            subject=args.subject,
            consent_store=args.consent_store,
        )
    if args.cmd == "doctor":
        return doctor(
            args.path,
            args.adapter,
            args.table,
            args.fmt,
            subject=args.subject,
            consent_store=args.consent_store,
        )
    if args.cmd == "consent":
        return consent_cmd(args.action, args.subject, args.store, args.by, args.fmt)
    if args.cmd == "adapters":
        return adapters(args.fmt)
    if args.cmd == "analyzers":
        return analyzers(args.fmt)
    if args.cmd == "label":
        return label(args.path, args.adapter, args.sample_size, args.store_path, args.table)
    if args.cmd == "score":
        return score(args.path, args.adapter, args.table, args.store_path, args.fmt)
    if args.cmd == "diff":
        return diff_cmd(args.report_a, args.report_b, args.fmt)
    return 2


if __name__ == "__main__":
    sys.exit(main())
