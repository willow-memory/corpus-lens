"""Adapter: Gemini CLI session JSONL (one file per session under a `chats/`
directory; one JSON record per line — a session-metadata line, then a message
per turn).

PROVENANCE — READ FROM THE WRITER'S SOURCE, NOT AN OBSERVED CORPUS. Unlike
`claude_code.py` (built and tested against this project's own real session
log), nobody on this project has a real Gemini CLI corpus to read bytes from.
This adapter is instead built by reading the code that WRITES these files —
`google-gemini/gemini-cli`, package `@google/gemini-cli-core`, commit
ed2ac40df67a319bf348bd7e3d10494696b31b38 on branch `main` (committed
2026-09-08, cloned and read 2026-09-11; resolved and fetched again to confirm
it exists before this citation was written):

  * `packages/core/src/services/chatRecordingTypes.ts` — the record shapes
    (`BaseMessageRecord`, `ConversationRecordExtra`, `ConversationRecord`,
    `PartialMetadataRecord`, `MetadataUpdateRecord`, `RewindRecord`).
  * `packages/core/src/services/chatRecordingService.ts` — where files are
    written: `<projectTempDir>/chats/session-<ts>-<id8>.jsonl` for a main
    session, first line always the metadata record; a SUBAGENT session is
    written under `<projectTempDir>/chats/<parentSessionId>/<id>.jsonl`
    (`// subagents are nested under the complete parent session id`) and its
    metadata line carries `"kind":"subagent"`.
  * `packages/core/src/utils/sessionUtils.ts` (`isIgnoredUserContent`) and
    `packages/core/src/utils/environmentContext.ts` — the machine-injected
    `<session_context>` block (cwd, date, OS, directory tree, memory) that is
    recorded as the session's first `user` turn, and `<hook_context>` blocks
    (`packages/core/src/core/client.ts`, `coreToolHookTriggers.ts`) injected
    into later `user` turns from external hooks.

THE HONEST CONSEQUENCE, STATED PLAINLY. Reading the writer's source is real
evidence — these are the literal field names and file-path rules the CLI
compiles and ships, not a guess at a plausible schema — but it is not a
substitute for parsing real bytes from a real corpus. It cannot catch a bug
that only exists between the source and the disk (an interrupted write, a
version skew between the code read here and the version that wrote your
files, a code path this reading missed). Every rule below cites the file and
symbol it came from so a future reader can re-check it against their own
installed version; nothing here is invented to fill a gap the source did not
answer. Treat this adapter as read-from-spec, unverified-against-a-corpus,
until someone runs it on a real `~/.gemini/tmp/*/chats/` tree and reports back.

THE `subagents/` QUESTION (BUGS.md), ANSWERED FOR THIS RUNTIME. Yes, Gemini
CLI nests delegated transcripts — but not the way Claude Code does. Claude
Code's giveaway is a literal `subagents` PATH COMPONENT, so a directory-name
filter suffices. Gemini CLI's subagent files sit under a directory named for
the PARENT SESSION's id (a UUID/promptId, not a fixed literal), so a
directory-name filter would silently miss it — there is no fixed string to
match. The only reliable signal is the explicit `"kind":"subagent"` field the
service itself writes into the session's metadata record
(`chatRecordingTypes.ts::PartialMetadataRecord.kind`). This adapter reads that
field rather than the path, and skips the whole file (every record counted as
a drop) when it says `subagent` — the same outcome as the claude-code fix,
reached by the one signal this runtime actually gives.

Robustness, matching the house rules: every record that is not a real message
(`$rewindTo`, `$set` metadata updates, the metadata record itself, an
`info`/`error`/`warning` UI-only record, an unparseable timestamp, empty text
after injection stripping) is COUNTED toward `dropped`, never silently
discarded. A malformed line or an unreadable file degrades to counted drops,
never a crash. Wall logic (day offsets, cross-midnight delta censoring,
opaque hashed refs, the quarantined base date) is NOT re-implemented here — it
is delegated to `ingest/_rows.py::assemble`, the same shared assembler the
database adapters use, so this adapter cannot quietly weaken it.
"""
from __future__ import annotations

from pathlib import Path

from ..model import Surface
from . import register
from ._rows import assemble
from .claude_code import _iter_lines, _parse_ts

#: Message types the recording service writes (`ConversationRecordExtra`).
#: Only `user` / `gemini` are turns; `info` / `error` / `warning` are CLI UI
#: bookkeeping (slash-command feedback, error banners) with no operator or
#: model authorship, the same "not a turn by design" bucket as Claude Code's
#: tool_use/tool_result records.
_ROLE = {"user": "operator", "gemini": "machine"}


def _content_text(content) -> str:
    """Best-effort text from a `PartListUnion`: a bare string, a single
    `{text: ...}` Part, or a list mixing strings and Parts. Non-text parts
    (functionCall, functionResponse, inlineData, ...) contribute nothing —
    the same "extract only text blocks" rule `claude_code.py` applies to
    Claude Code's content-block list."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        t = content.get("text")
        return t if isinstance(t, str) else ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return " ".join(parts)
    return ""


def _session_kind(lines) -> str | None:
    """The file's own declared kind ('main' | 'subagent' | None), read from
    the first record carrying `sessionId` + `projectHash` (the metadata
    record `chatRecordingService.ts` always writes first). Absent metadata
    (a truncated or otherwise malformed file) reads as unknown, not
    'subagent' — we do not guess a classification the file never stated."""
    for _, o in lines:
        if (isinstance(o, dict) and isinstance(o.get("sessionId"), str)
                and isinstance(o.get("projectHash"), str)):
            return o.get("kind")
    return None


@register("gemini-cli")
def ingest(path: str, corpus_id: str = "corpus"):
    root = Path(path)
    if root.exists() and not root.is_dir():
        raise NotADirectoryError(
            f"corpuslens adapters take a directory of *.jsonl, not a file: {path}")
    raw = []           # (date, epoch|None, session_key, role, text, real_ref)
    dropped = 0
    for f in sorted(root.rglob("*.jsonl")):
        rel = f.relative_to(root).as_posix()
        lines = list(_iter_lines(f))
        if _session_kind(lines) == "subagent":
            # the model's own delegated-task transcript, not the operator's —
            # counted, never hidden (BUGS.md's `subagents/` finding, this
            # runtime's shape: see the module docstring)
            dropped += len(lines)
            continue
        for i, o in lines:
            if not isinstance(o, dict):
                dropped += 1
                continue
            if isinstance(o.get("$rewindTo"), str) or isinstance(o.get("$set"), dict):
                dropped += 1                      # bookkeeping, not a turn
                continue
            if isinstance(o.get("sessionId"), str) and isinstance(o.get("projectHash"), str):
                dropped += 1                      # the metadata record itself
                continue
            if not isinstance(o.get("id"), str):
                dropped += 1                      # not a recognizable message record
                continue
            role = _ROLE.get(o.get("type"))
            if role is None:
                dropped += 1                      # info/error/warning, or an unknown type
                continue
            d, epoch = _parse_ts(o.get("timestamp"))
            if d is None:
                dropped += 1
                continue
            text = _content_text(o.get("content"))
            # injection stripping and the empty-after-strip drop both happen
            # inside `assemble` (it calls the same `authored_text` the other
            # adapters use for role=="operator") — not duplicated here.
            raw.append((d, epoch, rel, role, text, f"{rel}:{i+1}"))

    events, q, drop2 = assemble(raw, corpus_id, "gemini-cli/1", Surface.CLI)
    return events, q, dropped + drop2
