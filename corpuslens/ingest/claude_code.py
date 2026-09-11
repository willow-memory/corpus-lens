"""Adapter: Claude Code session JSONL (one file per session, `timestamp` log
field per event line, `message.content` blocks). Point it at a directory; it
walks `**/*.jsonl`.

Provenance rule (non-negotiable, earned the hard way): dates come from the
`timestamp` LOG FIELD only — never from date-strings inside content. Content
dates once inflated a resumption count 10x.

Robustness rules (every one earned in review):
  * Every line that fails to become an Event is COUNTED (`dropped`) and
    surfaced in the audit sentence — nothing silently discarded.
  * A single malformed line or an unreadable file NEVER aborts the scan; it
    degrades to a counted drop and the run continues.
  * Filenames are hashed to opaque ids before reaching an Event, and the
    session key is the path RELATIVE TO THE ROOT (not the bare stem), so two
    same-named files in different directories stay distinct threads.
  * `delta_prev_s` is censored (None) whenever the previous event was on a
    different day — a cross-midnight delta would let an analyzer pin the clock
    hour, which the wall forbids. Within-day tempo survives.
  * Naive timestamps (no offset) are read as UTC explicitly, so the same
    corpus yields identical deltas on any machine (never the host timezone).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..model import AuthorClass, CoarseTime, DataType, Event, Quarantine, Surface
from . import register, register_label_text
from .injection import authored_text

ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T")

# The four classifiers and the features they set moved to the top-level
# `corpuslens.classifiers` at 0.2.1: every other adapter, the labeller and the
# analyzers all needed them, and reaching into one adapter by name for a thing
# that was never an adapter's property is how that coupling stayed invisible.
from ..classifiers import (  # noqa: F401  (re-exported: adapters import them from here)
    AUTHORED, CLARIFY, CLASSIFIER_SET_VERSION, CODE_REF, DELIB, _features, _hash,
)
def _parse_ts(ts):
    if not (isinstance(ts, str) and ISO.match(ts)):
        return None, None
    try:
        d = datetime.date(int(ts[:4]), int(ts[5:7]), int(ts[8:10]))   # month 13 etc -> drop, not crash
    except ValueError:
        return None, None
    epoch = None
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:                       # naive -> read as UTC, not host tz
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        epoch = dt.timestamp()
    except Exception:
        pass
    return d, epoch


def _iter_lines(f: Path):
    """Yield (line_index, parsed_or_None). An unreadable file yields one
    sentinel so the caller can count it as a drop and move on — never crash.

    Blank / whitespace-only lines are skipped as structural whitespace and are
    NOT counted toward `dropped` — they are line separators, not input records.
    Every line that carries content but fails to become an Event IS counted."""
    try:
        with f.open(encoding="utf-8-sig", errors="replace") as fh:
            for i, ln in enumerate(fh):
                if not ln.strip():
                    continue
                try:
                    yield i, json.loads(ln)
                except Exception:
                    yield i, None
    except OSError:
        yield -1, None


#: A session directory holds the operator's thread; `subagents/` beside it holds
#: transcripts of agents the ASSISTANT dispatched. Those files have the same
#: shape and the same `"type": "user"` records — but the "user" in them is the
#: model writing a task prompt to its own subagent, not the person.
#:
#: Counting them corrupts exactly the measurement this tool exists for. Observed
#: 2026-09-11 on this project's own session log: including three subagent
#: transcripts moved `opener_median_words` from 11 to 516 and turned one thread
#: into four. `owner == subject` is the scope rule, and a subagent prompt has no
#: owner in it.
#:
#: Skipped records are COUNTED as drops, never silently discarded. Studying a
#: fleet's own traffic is a different instrument — the README names an
#: agent-fleet adapter as deliberately unbuilt, and this is not it.
SUBAGENT_DIRS = frozenset({"subagents"})


def _is_subagent(rel_posix: str) -> bool:
    return any(part in SUBAGENT_DIRS for part in rel_posix.split("/")[:-1])


#: The runtime marks dispatched traffic on the RECORD, not just by where the
#: file sits: every `user`/`assistant` record carries `isSidechain`. Observed
#: 2026-09-11 on this project's own session log — 459 records in the operator's
#: own thread, every one `False`; 1,634 records across seven subagent
#: transcripts, every one `True`. Perfect separation, and a first-class field
#: rather than a naming convention.
#:
#: The directory skip above stays as the outer guard (it avoids reading those
#: files at all). This is the inner one, and it is the more robust of the two:
#: a path check only works while the runtime keeps writing sidechains to a
#: directory with that exact name, whereas the field travels with the record.
#: The `gemini-cli` adapter reached the same conclusion from the other
#: direction — that runtime nests subagent logs under the PARENT SESSION'S id,
#: where a path filter finds nothing, so it keys on the record's own `kind`.
#: Two runtimes, one lesson: read the producer's own marking, not the layout.
def _is_sidechain_record(o: dict) -> bool:
    return o.get("isSidechain") is True


#: A compaction summary is the runtime writing a précis of the conversation so
#: far and handing it back in the USER role. Nobody typed it.
#:
#: It was already caught, but only by the prose branch in `injection.py` that
#: matches "This session is being continued from a previous conversation" — a
#: match on the text a summary happens to open with. That is the same fragility
#: the `subagents/` path check had before `isSidechain` replaced it: it holds
#: exactly as long as the wording does.
#:
#: PROVENANCE, because this one is mixed and the mix matters. That compaction
#: records exist on disk was verified by the owner grepping his own transcripts
#: on another machine, which found `"subtype":"compact_boundary"` in three
#: files. This session's own corpus contains none — it never compacted — so the
#: absence proved nothing either way, and an early grep here that appeared to
#: find them was matching a message that merely discussed them.
#:
#: The FIELD NAME below comes from a description of the producer's source that
#: nobody on this side can reach, and is therefore unverified. It is written
#: anyway because the check is inert if the description is wrong: a record that
#: never carries the field is never skipped by it, and no human turn carries
#: it. The prose branch stays as the belt to this pair of braces. If a real
#: compacted transcript ever reaches this repository, it belongs in the
#: fixtures, and this comment should be rewritten to cite it instead.
def _is_compaction_summary(o: dict) -> bool:
    return o.get("isCompactSummary") is True


@dataclass(frozen=True)
class LabelCorpus:
    """The fixed return shape of `label_text` below — see its docstring for
    why `text_by_ref` is allowed to exist at all outside the Guard, and the
    conditions that must stay true for that to remain a justification rather
    than an oversight."""
    events: list
    quarantine: Quarantine
    dropped: int
    text_by_ref: dict


def _ingest_impl(path: str, corpus_id: str, want_text: bool):
    """The one parse of a claude-code corpus. `want_text` is an INTERNAL
    switch between the two fixed-arity public functions below — it never
    reaches a caller, and it never changes the shape of what either public
    function returns. `text_by_ref` is `{}` when `want_text` is False, so a
    caller can always unpack this 4-tuple the same way regardless."""
    root = Path(path)
    if root.exists() and not root.is_dir():
        raise NotADirectoryError(f"corpuslens adapters take a directory of *.jsonl, not a file: {path}")
    raw = []          # (date, epoch|None, session_key, role, text, real_ref)
    dropped = 0
    for f in sorted(root.rglob("*.jsonl")):
        rel = f.relative_to(root).as_posix()
        if _is_subagent(rel):
            # the model's own dispatch traffic, not the operator's — counted,
            # not hidden (one drop per record in the file)
            dropped += sum(1 for _ in _iter_lines(f))
            continue
        for i, o in _iter_lines(f):
            if not isinstance(o, dict):
                dropped += 1
                continue
            if o.get("type") not in ("user", "assistant"):
                dropped += 1
                continue
            if _is_sidechain_record(o):
                # dispatched traffic that landed outside a `subagents/` path —
                # the model prompting its own agent is not the owner. Counted.
                dropped += 1
                continue
            if _is_compaction_summary(o):
                # the runtime's own précis of the thread, handed back in the
                # user role. Not a prompt, whatever it opens with. Counted.
                dropped += 1
                continue
            d, epoch = _parse_ts(o.get("timestamp"))
            if d is None:
                dropped += 1
                continue
            msg = o.get("message")
            if not isinstance(msg, dict):
                msg = {}
            content = msg.get("content")
            if isinstance(content, list):
                text = " ".join(b.get("text") or "" for b in content
                                if isinstance(b, dict) and b.get("type") == "text")
            else:
                text = content if isinstance(content, str) else ""
            raw.append((d, epoch, rel, o["type"], text, f"{rel}:{i+1}"))

    if not raw:
        return [], Quarantine(), dropped, {}

    base = min(r[0] for r in raw)
    by_session: dict = {}
    for rec in raw:
        by_session.setdefault(rec[2], []).append(rec)
    for recs in by_session.values():
        recs.sort(key=lambda r: (r[1] is None, r[1] if r[1] is not None else 0.0))

    events = []
    ref_map: dict = {}
    text_by_ref: dict = {}
    for session, recs in by_session.items():
        sid = _hash(corpus_id, session)
        prev_epoch = None
        prev_day = None
        for d, epoch, _, role, text, real_ref in recs:
            day_offset = (d - base).days
            if role == "user":
                text, stripped = authored_text(text)
                author, dtype = AuthorClass.OPERATOR, DataType.PROMPT
            else:
                author, dtype, stripped = AuthorClass.MACHINE, DataType.RESPONSE, False
            if not text.strip():
                dropped += 1
                if epoch is not None:               # keep the clock advancing
                    prev_epoch, prev_day = epoch, day_offset
                continue
            # censor cross-day deltas: a midnight-crossing gap would pin the hour
            same_day = (prev_day == day_offset)
            delta = (epoch - prev_epoch) if (epoch is not None and prev_epoch is not None
                                             and same_day) else None
            if epoch is not None:
                prev_epoch, prev_day = epoch, day_offset
            opaque = _hash(sid, real_ref)
            ref_map[opaque] = real_ref
            if want_text:
                text_by_ref[opaque] = text
            events.append(Event(
                event_id=opaque, corpus_id=corpus_id, adapter_id="claude-code/1",
                source_ref=opaque, thread_id=sid, surface=Surface.CLI,
                author_class=author, data_type=dtype,
                time=CoarseTime(day_offset=day_offset, delta_prev_s=delta),
                features=_features(text, stripped)))
    quarantine = Quarantine(base_date_iso=base.isoformat(), ref_map=ref_map)
    return events, quarantine, dropped, text_by_ref


@register("claude-code")
def ingest(path: str, corpus_id: str = "corpus"):
    """(events, quarantine, dropped) — always exactly this 3-tuple, for every
    call, with no keyword that changes its shape. This is the ONLY entry point
    every other adapter and the whole CLI (`run`, `doctor`, `score`) call
    through `ingest.get(name)(path, ...)`; see `label_text` below for the
    separate, differently-shaped function `corpuslens label` uses instead of
    overloading this one."""
    events, quarantine, dropped, _ = _ingest_impl(path, corpus_id, want_text=False)
    return events, quarantine, dropped


@register_label_text("claude-code")
def label_text(path: str, corpus_id: str = "corpus") -> LabelCorpus:
    """Everything `corpuslens label` needs: the same Events `ingest()` would
    produce, plus `text_by_ref` — `{opaque source_ref: the turn's own text}`,
    the SAME de-injected string `_features()` classified. Always this one
    `LabelCorpus` shape; there is no flag that changes it.

    WHY A HASH-TO-CONTENT MAP IS ALLOWED HERE, WHEN THE STRUCTURALLY IDENTICAL
    `Quarantine.ref_map` IS NOT (read this before touching this function or
    copying its shape into another adapter). `ref_map` maps
    `source_ref -> the real file:line locator`, gated behind the Guard because
    a locator can leak a filename's embedded date; this maps
    `source_ref -> the turn's own text`, and it is handed back with NO Guard
    at all. Both are "opaque hash -> the real thing behind it" — exactly the
    shape the wall exists to gate — so the omission needs its own reasoning,
    not just a comment saying it's fine:

      1. **owner == subject.** (README, "Scope"; guard.py's "not an
         adversarial sandbox against the machine's OWNER".) `label` is the
         corpus's own owner reading their own turns to grade a classifier —
         the one case this project has always said the wall does not, and
         should not, stop.
      2. **Nothing new is exposed.** `ingest()` already reads this exact text
         at parse time to compute `_features()`; this function does not open
         a door `ingest()` keeps shut, it just keeps a string `ingest()`
         would otherwise compute booleans from and then drop.
      3. **It is ephemeral, not a second quarantine.** Built fresh in memory
         for one `label` invocation, from the caller's own local files, and
         never written to disk by this function or anything it calls.

    THE CONDITIONS THAT MUST STAY TRUE for that reasoning to keep holding.
    If code changes so that any of these is no longer true, `label_text` needs
    Guard-style gating like `Quarantine.ref_map` — this docstring stops being
    a justification and starts being a stale excuse:

      * `text_by_ref` is never attached to an `Event` — an `Event.features`
        value is always a bool/int/None, never a string (pinned by
        `tests/test_label.py::LabelTextSeamTests`).
      * `text_by_ref` never reaches a renderer, `run`, `doctor`, or any
        report — it is read only inside `cli.label`'s own interactive loop
        (pinned by the same test class, driving `run`/`doctor` on this
        corpus and asserting no turn text appears in their output).
      * `text_by_ref` is never written to a label store — `label.py`'s
        `save_store` writes only `{source_ref, classifier, label}` (pinned by
        `tests/test_label.py::LabelCliTests`).
      * It is produced fresh per call from local files, never cached to disk,
        never returned from a network call, and never reused across a
        process boundary.
    """
    events, quarantine, dropped, text_by_ref = _ingest_impl(path, corpus_id, want_text=True)
    return LabelCorpus(events=events, quarantine=quarantine, dropped=dropped,
                       text_by_ref=text_by_ref)
