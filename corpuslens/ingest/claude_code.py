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
from . import register, register_default_path, register_label_text
from .drops import (ATTACHMENT, COMPACTION_SUMMARY, DropCounts, EMPTY_TURN,
                    HARNESS_BOOKKEEPING, MISSING_TIMESTAMP, SUBAGENT, THINKING,
                    TOOL_TRAFFIC, UNPARSEABLE_LINE)
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


#: A user-role record the HARNESS wrote, not the operator. Two fields, both
#: first-class on the record, both observed 2026-09-12 by walking this
#: project's owner's own 18-hour session log (the same log the
#: `<task-notification>` fix below measured):
#:
#:   * `isMeta: true` — the runtime re-issuing "Continue from where you left
#:     off." after a context reset. Eight of them in that log, every one
#:     counted as an operator prompt before this check; the owner never typed
#:     one. They carry no wrapper tag, so `injection.py` cannot see them, and
#:     the text is exactly what a person might type, so a prose match would
#:     be wrong in both directions.
#:   * `origin: {"kind": ...}` — the runtime naming who authored the turn.
#:     Every turn the owner typed carried `origin.kind == "human"` (23 of 23,
#:     each also `promptSource: "sdk"`); every finished background task
#:     carried `origin.kind == "task-notification"` (122 of 122), and NO human
#:     turn carried `isMeta`. Perfect separation on the producer's own marking,
#:     the same lesson as `isSidechain` above.
#:
#: The `origin` half also corrects a mis-bucketing: a `<task-notification>`
#: turn was stripped to nothing by the tag filter and then counted as an
#: EMPTY_TURN — "should have been a turn and failed" — which put 122 correct
#: drops on the malformed side of the doctor's warning (36.8% malformed on a
#: corpus with nothing malformed in it). Keyed on the field, it is structural.
#:
#: Fail-open on absence, by design: a record with neither field (an older
#: harness, or another producer) is exactly as much a turn as it was before.
#: Only a PRESENT `origin.kind` that is not "human" excludes a record — the
#: field is read, never inferred.
def _is_harness_authored(o: dict) -> bool:
    if o.get("isMeta") is True:
        return True
    origin = o.get("origin")
    if isinstance(origin, dict) and "kind" in origin:
        return origin.get("kind") != "human"
    return False


#: Top-level `type` values, besides "user"/"assistant", this harness is known
#: to write — observed directly by walking THIS PROJECT'S OWN session log
#: (2026-09-11, the same log BUGS.md's Open #1 measured): "attachment" (an
#: attachment record), and "last-prompt", "atis-latch", "mode",
#: "queue-operation", "system" (harness bookkeeping — session/UI/queue state,
#: no operator or model authorship). See BUGS.md's "Fixed" entry for this item
#: for the exact counts. A `type` outside "user"/"assistant" and outside these
#: sets is still not a turn — only "user"/"assistant" records carry a
#: `message` at all — but this adapter does not claim to know MORE than that
#: about a shape nobody has confirmed yet, so it falls into the same
#: `HARNESS_BOOKKEEPING` bucket rather than a guessed, more specific one.
_ATTACHMENT_RECORD_TYPES = frozenset({"attachment"})

#: Content-BLOCK `type` values (inside a user/assistant record's
#: `message.content` list) that make the record's extracted text empty BY
#: DESIGN rather than by failure. `redacted_thinking` and `image`/`document`
#: are not confirmed against real bytes the way `tool_use`/`tool_result`/
#: `thinking` are (from this project's own log), but they are the documented
#: Anthropic content-block shapes for the same two classes ("thinking" and
#: "attachment") already established here, so classifying them the same way
#: is a shape-name extension, not a guess at new evidence.
_TOOL_BLOCK_TYPES = frozenset({"tool_use", "tool_result"})
_THINKING_BLOCK_TYPES = frozenset({"thinking", "redacted_thinking"})
_ATTACHMENT_BLOCK_TYPES = frozenset({"image", "document"})


def _drop_reason_for_type(t) -> str:
    """The reason a non-user/assistant top-level record is not a turn — see
    the record-type sets above. Closed vocabulary in, closed vocabulary out:
    never the raw `type` string itself (ingest/drops.py's whole point)."""
    if t in _ATTACHMENT_RECORD_TYPES:
        return ATTACHMENT
    return HARNESS_BOOKKEEPING


def _classify_contentless(content) -> str:
    """The reason a user/assistant record's `message.content` produced no
    TEXT — inspects the content BLOCK TYPES present (never their text) to
    tell "not a turn by design" (tool traffic, thinking, an attachment) apart
    from "a text block was there and it came out blank", which is a genuine
    empty turn and stays malformed (counted by the caller, not here — this
    function only names the reason for the not-a-turn-by-design case; an
    empty TEXT block is reported by the caller as `EMPTY_TURN`)."""
    if isinstance(content, list) and content:
        kinds = {b.get("type") for b in content if isinstance(b, dict)}
        if kinds & _TOOL_BLOCK_TYPES:
            return TOOL_TRAFFIC
        if kinds & _THINKING_BLOCK_TYPES:
            return THINKING
        if kinds & _ATTACHMENT_BLOCK_TYPES:
            return ATTACHMENT
        if "text" not in kinds:
            # Blocks are present but none are text/tool/thinking/attachment —
            # an unrecognised block shape. Not a turn either way, but this
            # adapter cannot name it any more precisely than that.
            return HARNESS_BOOKKEEPING
    return EMPTY_TURN


@dataclass(frozen=True)
class LabelCorpus:
    """The fixed return shape of `label_text` below — see its docstring for
    why `text_by_ref` is allowed to exist at all outside the Guard, and the
    conditions that must stay true for that to remain a justification rather
    than an oversight."""
    events: list
    quarantine: Quarantine
    drops: DropCounts
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
    drops = DropCounts()
    for f in sorted(root.rglob("*.jsonl")):
        rel = f.relative_to(root).as_posix()
        if _is_subagent(rel):
            # the model's own dispatch traffic, not the operator's — counted,
            # not hidden (one drop per record in the file)
            drops.add(SUBAGENT, sum(1 for _ in _iter_lines(f)))
            continue
        for i, o in _iter_lines(f):
            if not isinstance(o, dict):
                drops.add(UNPARSEABLE_LINE)
                continue
            if o.get("type") not in ("user", "assistant"):
                drops.add(_drop_reason_for_type(o.get("type")))
                continue
            if _is_sidechain_record(o):
                # dispatched traffic that landed outside a `subagents/` path —
                # the model prompting its own agent is not the owner. Counted.
                drops.add(SUBAGENT)
                continue
            if _is_compaction_summary(o):
                # the runtime's own précis of the thread, handed back in the
                # user role. Not a prompt, whatever it opens with. Counted.
                drops.add(COMPACTION_SUMMARY)
                continue
            if o.get("type") == "user" and _is_harness_authored(o):
                # the harness's own resume prompt, or a turn whose `origin`
                # names a non-human author — nobody typed it. Counted.
                drops.add(HARNESS_BOOKKEEPING)
                continue
            d, epoch = _parse_ts(o.get("timestamp"))
            if d is None:
                drops.add(MISSING_TIMESTAMP)
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
            if not text:
                # Nothing to featurize yet — before injection stripping, which
                # only ever REMOVES text, so an empty extraction here can only
                # get emptier there. Decide now, while the content blocks that
                # explain WHY are still in hand: tool traffic, thinking, an
                # attachment (not a turn by design) vs. a text block that was
                # simply blank (a genuine empty turn, malformed).
                reason = _classify_contentless(content)
                if reason == EMPTY_TURN:
                    # A plain-string content field, or a text block, came back
                    # empty. User-role text still goes through injection
                    # stripping below in case a wrapper's OWN stripping would
                    # matter here — it would not change an already-empty
                    # string, so counting it now (rather than deferring to the
                    # assembly loop) is equivalent and keeps this one site
                    # honest about what it saw.
                    drops.add(EMPTY_TURN)
                else:
                    drops.add(reason)
                continue
            raw.append((d, epoch, rel, o["type"], text, f"{rel}:{i+1}"))

    if not raw:
        return [], Quarantine(), drops, {}

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
                # Injection stripping (authored_text, user role only) removed
                # everything — a wrapper the harness injects with no authored
                # text left over. Turn-shaped, dated, correctly roled, and
                # empty: malformed, not structural (BUGS.md, Open #1, Fixed).
                drops.add(EMPTY_TURN)
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
    return events, quarantine, drops, text_by_ref


@register_default_path("claude-code", "~/.claude/projects")
@register("claude-code")
def ingest(path: str, corpus_id: str = "corpus"):
    """(events, quarantine, drops) — always exactly this 3-tuple, for every
    call, with no keyword that changes its shape (`drops` is a
    `ingest.drops.DropCounts`, not a bare int — see `ingest/__init__.py`'s
    module docstring for the contract and why). This is the ONLY entry point
    every other adapter and the whole CLI (`run`, `doctor`, `score`) call
    through `ingest.get(name)(path, ...)`; see `label_text` below for the
    separate, differently-shaped function `corpuslens label` uses instead of
    overloading this one."""
    events, quarantine, drops, _ = _ingest_impl(path, corpus_id, want_text=False)
    return events, quarantine, drops


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
    events, quarantine, drops, text_by_ref = _ingest_impl(path, corpus_id, want_text=True)
    return LabelCorpus(events=events, quarantine=quarantine, drops=drops,
                       text_by_ref=text_by_ref)
