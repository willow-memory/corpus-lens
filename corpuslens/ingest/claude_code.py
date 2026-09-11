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
from pathlib import Path

from ..model import AuthorClass, CoarseTime, DataType, Event, Quarantine, Surface
from . import register
from .injection import authored_text

ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T")

# CODE_REF: require CODE-ADJACENT context, not bare English words. Every
# alternative needs a code shape (a call, a dotted call, a fence, a source
# file, a traceback frame, a CamelCase Error/Exception, a real def/import).
# Case-sensitive on the keyword/Error branches so prose "exception"/"error"
# does not match. English-and-Python shaped, disclosed: the source-file
# branch knows a short fixed list of extensions (py/js/ts/rs/go/rb/java/sql/sh
# — nine here, counted from this regex; other docs round it to "eight" and
# should be checked against this list rather than the reverse) and the
# traceback branch is Python's own "Traceback (most recent call last)" /
# "line N, in" — a real code corpus in an unlisted language or file type
# scores identically to one with no code in it at all.
CODE_REF = re.compile(
    # Call detection matches the reference study's methodology (the READ regex in
    # operator_reading_analysis): an EMPTY-parens call foo() or a dotted method
    # call obj.method( — NOT bare word(word). Bare word(arg) fires on prose asides
    # ("change(s)", "see you(soon)", "kind of(ish)") and inflated code_ref_pct to
    # 100% on a code-free corpus; it is also broader than the reference the number
    # is compared against. Empty/dotted calls do not occur in ordinary prose.
    r"\b[A-Za-z_]\w*\(\s*\)"                    # empty call: foo()
    r"|\b[A-Za-z_]\w*\.[A-Za-z_]\w*\("          # method call: obj.method(
    r"|`[^`]+`|```"                              # inline / fenced code
    r"|\b\w+\.(py|js|ts|rs|go|rb|java|sql|sh)\b"  # source file
    r"|Traceback \(most recent call last\)"
    r"|\bline\s+\d+,\s+in\b"                     # python traceback frame
    r"|\b\w+(Error|Exception)\b"                # ValueError, KeyError (needs prefix)
    r"|\breturn\s+\w+\("                         # return a call
    r"|\b(def|class|async def)\s+\w+\s*\("     # def/class with a param list
    r"|\bfrom\s+[\w.]+\s+import\b"              # from x import y
    r"|\bimport\s+[a-z]\w*\.\w",                # import a.b (dotted module)
)
# AUTHORED: pasted code. Every branch requires a CODE SHAPE, not a bare keyword
# — prose openers like "let me know", "static electricity", "var was short for"
# must not count (they inflated authored_code_pct to 40% on a pure-prose corpus
# in review). No generic `x = ...` branch: "Budget = 500", "Plan = [buy milk]",
# "Verdict = (guilty)" are prose; isolated assignments are weak evidence and
# under-counting beats over-claiming "you write code". Case-sensitive.
# English-and-Python shaped, disclosed: the branches below cover Python, JS/TS,
# Java/C#, Go/Rust (func/fn), shell and SQL block syntax — a handful of
# languages, not "code" in general. Real pasted code in a language with none
# of these shapes (or a Python-family dialect whose block syntax differs)
# scores identically to no pasted code at all.
AUTHORED = re.compile(
    r"```"
    r"|^\s*(def|class|async\s+def)\s+\w+\s*\("        # def foo( / class Bar(
    r"|^\s*for\s+\w+\s+in\s+[^\n]*:\s*$"               # for x in ...:
    r"|^\s*(while|if|elif)\b[^\n]*[<>=!(][^\n]*:\s*$" # while/if with an operator/paren, ending ':'
    r"|^\s*(try|except|finally|else)\s*:\s*$"          # bare block keyword line
    r"|^\s*(public|private|protected|static)(\s+(public|private|protected|static|final|abstract|synchronized))*\s+[\w<>\[\].]+\s+\w+\s*[({=;]"  # java/c# decl (1+ modifiers)
    r"|^\s*(func|fn)\s+\w+\s*\("                        # func name(
    r"|^\s*(const|let|var)\s+\w+\s*[:=]"                # const/let/var x = | x:
    # imports anchored to a code shape: a bare module path (optionally `as x`) to
    # end of line, or a full `from x import y` list — so prose "import export
    # business is booming" / "import duty" do NOT match
    r"|^\s*import\s+[\w.]+(\s+as\s+\w+)?\s*$"
    r"|^\s*from\s+[\w.]+\s+import\s+(\*|[\w.]+(\s*,\s*[\w.]+)*)\s*$"
    r"|^\s*[A-Za-z_]\w*\([^)]*\)\s*$"                   # a line that is just a call: print(x)
    r"|^\s*#!\s*/|^\s*export\s+\w+="                    # shell: shebang / export VAR=
    r"|\|\s*(grep|awk|sed|sort|uniq|head|tail|xargs|wc|jq)\b"  # shell pipe chain
    r"|\b(SELECT|INSERT|UPDATE|DELETE)\b[^\n]*\b(FROM|INTO|SET|WHERE|VALUES)\b"
    r"|console\.log\(|println!\(|System\.out\.",
    re.M,
)
# DELIB and CLARIFY are both lists of ENGLISH phrases — same disclosed limit as
# CODE_REF/AUTHORED's eight file extensions and handful of languages' block
# syntax, just for prose rather than code. A corpus conducted in another
# language matches neither, and looks identical to a corpus where the
# operator never deliberated / the machine never asked a clarifying question.
# Undercounting, not a bug — but it is why `composition_mix` and
# `clarification_pull` refuse rather than report 0.0% once the sample is
# large enough that "detected nothing" would otherwise read as a finding (see
# `analyze/composition.py`).
DELIB = re.compile(
    r"\btalk (to me )?about\b|let'?s (talk|discuss|explore)|\bdiscuss\b|pros?\s*(and|/|\-)\s*cons?"
    r"|trade.?offs?|think (through|about)\b|what do you think"
    r"|\byour thoughts\b|\bany thoughts\b|thoughts on\b|thoughts\?"
    r"|help me (think|understand|decide|figure|weigh)|walk me through"
    r"|weigh (the |our |my )?options\b|what (are|were) (the |my |our )?options|\b(the|my|our) options\b"
    r"|brainstorm|i'?m (thinking|wondering|considering)|convince me|push back", re.I)
CLARIFY = re.compile(
    r"do you (mean|want)|would you like|should i\b|which (one|of|do|would|approach)"
    r"|to clarify|can you confirm|just to confirm|one question|quick question", re.I)


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8", "replace")).hexdigest()[:16]


def _features(text: str, stripped: bool) -> dict:
    return {
        "word_count": len(text.split()),
        "char_count": len(text),
        "code_fenced": text.count("```") >= 2,
        "code_authored": bool(AUTHORED.search(text)),
        "code_ref": bool(CODE_REF.search(text)),
        "delib": bool(DELIB.search(text)),
        "question": "?" in text,
        "clarify": bool(CLARIFY.search(text)),
        "injected_stripped": stripped,
    }


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


@register("claude-code")
def ingest(path: str, corpus_id: str = "corpus"):
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
        return [], Quarantine(), dropped

    base = min(r[0] for r in raw)
    by_session: dict = {}
    for rec in raw:
        by_session.setdefault(rec[2], []).append(rec)
    for recs in by_session.values():
        recs.sort(key=lambda r: (r[1] is None, r[1] if r[1] is not None else 0.0))

    events = []
    ref_map: dict = {}
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
            events.append(Event(
                event_id=opaque, corpus_id=corpus_id, adapter_id="claude-code/1",
                source_ref=opaque, thread_id=sid, surface=Surface.CLI,
                author_class=author, data_type=dtype,
                time=CoarseTime(day_offset=day_offset, delta_prev_s=delta),
                features=_features(text, stripped)))
    return events, Quarantine(base_date_iso=base.isoformat(), ref_map=ref_map), dropped
