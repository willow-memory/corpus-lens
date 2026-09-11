"""Injection filter — operator-typed vs machine-injected.

Cross-runtime comparison is corrupted by injected context (the Cursor
front-loading finding, 2026-07-16: median 3202w -> 15w once stripped). This
filter is applied at ingest so nothing downstream ever mistakes tooling for a
person. Regexes are conservative: strip only wrappers KNOWN to be injected.
"""
from __future__ import annotations

import re

#: Wrapper tags a runtime injects into the operator's turn. Enumerated, never
#: guessed: each one was observed wrapping machine-supplied context in a real
#: corpus. Stripping an unknown `<tag>` generically would eat authored content
#: (XML in a question, a code block), so the list stays explicit.
#:
#: The second group was added 2026-09-07 from Cursor's `store.db` corpus, where
#: `<user_info>` alone left a 3617-word median opener — the front-loading
#: finding again, with the same shape and different tag names. These are the
#: same runtime's wrappers as the ones already listed; the `cursor` adapter
#: reads them too, so its openers get shorter (more accurate) as well.
_INJECTED_TAGS = (
    "user_info", "environment_details", "additional_data", "timestamp",
    # Cursor store.db, observed 2026-09-07
    "always_applied_workspace_rule", "always_applied_workspace_rules",
    "agent_transcripts", "transcript_location", "git_status",
    "rules", "user_rule", "agent_skill", "agent_skills",
    "summary_content", "hooks_context", "system_notification",
    "system_reminder", "mcp_instructions", "mcp_meta_tools",
    "mcp_meta_tool_servers", "dynamic_tools", "dynamic_tool_catalog",
    "dynamic_tool_namespaces", "available_subagent_types",
    "available_subagent_models", "mermaid_syntax", "todo_update",
    # Claude Code harness, observed 2026-09-11 in this project's own session
    # log. A background task finishing delivers its whole result in the USER
    # role: three such turns ran 1728, 902 and 1246 words against a human whose
    # median was 28, and `injected_stripped` was False on every one of them.
    # Same front-loading shape as the Cursor finding, a different runtime's tag.
    # The inner tags (task-id, status, summary, result, usage …) are children of
    # this one, so stripping the wrapper takes them with it.
    "task-notification",
    # Gemini CLI (`google-gemini/gemini-cli`, package `@google/gemini-cli-core`),
    # read from source 2026-09-11, not from an observed corpus — see the
    # provenance note in `ingest/gemini_cli.py`. `<session_context>` is the
    # cwd/date/OS/directory-tree/memory block `environmentContext.ts` inserts
    # as the session's first "user" turn; `<hook_context>` wraps output an
    # external hook returns, injected into a later "user" turn from
    # `core/client.ts` and `coreToolHookTriggers.ts`. Gemini CLI's own resume
    # code (`utils/sessionUtils.ts::isIgnoredUserContent`) already treats both
    # prefixes as not-a-real-user-turn for its own purposes — the same
    # front-loading shape as every tag above, this runtime's names for it.
    "session_context", "hook_context",
)

#: An injected block may carry attributes — `<mcp_instructions description="…">`
#: is the common Cursor form. Matching only a bare `<tag>` left 277 turns with a
#: multi-thousand-word "opener" that no human typed.
_OPEN = r"<{t}(?:\s[^>]*)?>"

#: Whole-turn machine text with no wrapper at all: a runtime that compacts a
#: conversation re-injects the summary AS a user turn. It is not a prompt, and
#: counting it as one is what put the opener median in the thousands. Anchored
#: at the start and consuming the turn, so a human quoting one of these phrases
#: mid-message is untouched.
MACHINE_TURN = re.compile(
    r"\A\s*(?:"
    r"\[Previous conversation summary\]"
    r"|Your conversation was summarized due to"
    r"|This session is being continued from a previous conversation"
    r"|The beginning of the above subagent result"
    r").*",
    re.DOTALL | re.IGNORECASE,
)

INJECTED = re.compile(
    "|".join([r"<system-reminder>.*?</system-reminder>"]
             + [_OPEN.format(t=t) + rf".*?</{t}>" for t in _INJECTED_TAGS]
             # An unclosed injected block (truncated at a context boundary)
             # still is not the operator's text: consume to the next open tag
             # or the end rather than leaving thousands of words behind.
             # `-` is in the terminator class because a wrapper name may carry
             # one (`task-notification`): without it an unclosed block would run
             # straight through the next wrapper instead of stopping at it.
             + [_OPEN.format(t=t) + r"(?:(?!<[a-z_-]{3,32}[\s>]).)*\Z" for t in _INJECTED_TAGS]),
    re.DOTALL | re.IGNORECASE,
)
USER_QUERY = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL)


def authored_text(raw: str) -> tuple[str, bool]:
    """Return (operator-authored text, was_anything_stripped)."""
    stripped = False
    m = USER_QUERY.findall(raw)
    if m:
        raw = " ".join(m)
        stripped = True
    if MACHINE_TURN.match(raw):
        return "", True          # not a prompt at all — the caller counts it
    cleaned = INJECTED.sub(" ", raw)
    if cleaned != raw:
        stripped = True
    return cleaned.strip(), stripped
