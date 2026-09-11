"""Adapter: Cursor session JSONL (role/message lines; the runtime injects a
`<timestamp>` tag at the head of user text blocks and wraps the authored
query in `<user_query>`). Dates come from the injected tag at BLOCK START
only — a content-quoted tag mid-text does not count.

CONSERVATIVE BY CONSTRUCTION: only user text BLOCKS whose text starts with a
recognizable `<timestamp>` tag can be dated. Every non-dated line AND every
non-dated block is COUNTED toward `dropped` — nothing is silently discarded
(the old version hid most of the corpus). Block index is part of the ref, so
two dated blocks on one line get distinct opaque ids. A malformed line or an
unreadable file degrades to a counted drop, never a crash. Session identity is
the path relative to the root, so same-named files in different directories
stay distinct.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from ..model import AuthorClass, CoarseTime, DataType, Event, Quarantine, Surface
from . import register
from ..classifiers import _features, _hash
from .claude_code import _iter_lines
from .drops import (DropCounts, EMPTY_TURN, MISSING_TIMESTAMP,
                    NOT_A_TURN_RECORD, UNPARSEABLE_LINE)
from .injection import authored_text

MON = {m: i + 1 for i, m in enumerate((
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"))}
TAG = re.compile(r"^\s*<timestamp>\w+,\s+(\w+)\s+(\d{1,2}),\s+(\d{4})")


@register("cursor")
def ingest(path: str, corpus_id: str = "corpus"):
    root = Path(path)
    if root.exists() and not root.is_dir():
        raise NotADirectoryError(f"corpuslens adapters take a directory of *.jsonl, not a file: {path}")
    raw = []          # (date, session_key, text, real_ref, stripped)
    drops = DropCounts()
    for f in sorted(root.rglob("*.jsonl")):
        rel = f.relative_to(root).as_posix()
        for i, o in _iter_lines(f):
            if not isinstance(o, dict):
                drops.add(UNPARSEABLE_LINE)
                continue
            if o.get("role") != "user":
                # assistant/system/tool lines — this adapter is conservative
                # BY CONSTRUCTION and only ever extracts operator text (see
                # module docstring); not a turn this adapter reports, not a
                # failure either.
                drops.add(NOT_A_TURN_RECORD)
                continue
            msg = o.get("message")
            if not isinstance(msg, dict):
                msg = {}
            blocks = [b for b in msg.get("content") or []
                      if isinstance(b, dict) and b.get("type") == "text"]
            if not blocks:
                drops.add(NOT_A_TURN_RECORD)
                continue
            for bi, blk in enumerate(blocks):
                txt = blk.get("text") or ""
                m = TAG.match(txt)
                if not m or m[1] not in MON:
                    drops.add(MISSING_TIMESTAMP)    # every non-dated block counted
                    continue
                try:
                    d = datetime.date(int(m[3]), MON[m[1]], int(m[2]))
                except ValueError:
                    drops.add(MISSING_TIMESTAMP)
                    continue
                text, stripped = authored_text(txt)
                if not text:
                    drops.add(EMPTY_TURN)
                    continue
                raw.append((d, rel, text, f"{rel}:{i+1}:{bi}", stripped))
    if not raw:
        return [], Quarantine(), drops
    base = min(r[0] for r in raw)
    # sort per session by date (day granularity — cursor has no clock time), so
    # the opener is the chronologically first prompt, matching the claude adapter
    raw.sort(key=lambda r: (r[1], r[0]))
    events = []
    ref_map: dict = {}
    for d, session, text, real_ref, stripped in raw:
        sid = _hash(corpus_id, session)
        opaque = _hash(sid, real_ref)
        ref_map[opaque] = real_ref
        events.append(Event(
            event_id=opaque, corpus_id=corpus_id, adapter_id="cursor/1",
            source_ref=opaque, thread_id=sid, surface=Surface.IDE,
            author_class=AuthorClass.OPERATOR, data_type=DataType.PROMPT,
            time=CoarseTime(day_offset=(d - base).days),
            features=_features(text, stripped)))
    return events, Quarantine(base_date_iso=base.isoformat(), ref_map=ref_map), drops
