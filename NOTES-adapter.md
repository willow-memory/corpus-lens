# Adapter research notes — "More runtimes on the same seam" (IDEAS.md)

Scope: research all four candidates named in IDEAS.md's `## Adapters` bullet
("More runtimes on the same seam" — Codex CLI, Gemini CLI, aider, opencode),
build ONE adapter on the evidence that verifies best, and answer the
`subagents/` question (BUGS.md) for that runtime. This file is the research
record; `README.md` and `IDEAS.md` are untouched per instructions (other
agents are editing them in parallel).

**Housekeeping note.** This worktree was created from a commit before the
"More runtimes on the same seam" bullet was merged to `IDEAS.md`. I did not
build anything against a guess at the missing bullet — all research below
happened after `git fetch origin main && git merge origin/main` pulled it in,
and the merged bullet matches what I'd been told directly. Nothing here was
built blind.

Branch: `claude/expand-adapter`. Built: `corpuslens/ingest/gemini_cli.py`,
two new tags in `injection.py`, `tests/test_gemini_cli.py`.

---

## The constraint this task is about

corpus-lens's rule: a format is read from real bytes, never guessed. Nobody on
this project has a real corpus for any of these four runtimes — no `.jsonl`
pulled from someone's actual `~/.codex`, `~/.gemini`, `~/.aider`, or
`~/.local/share/opencode`. The best available substitute, per the task
instructions, is reading the runtime's own open-source code that WRITES the
log. That is real evidence (literal field names and file-path rules the
maintainers compile and ship) but it is **not** the same class of evidence as
`claude_code.py` and `cursor_store.py` have (bytes from a real corpus,
including this project's own dogfood log). The adapter this produces should be
read as **verified against source, unverified against a corpus** — stated in
its own docstring, not just here.

All four repos were cloned shallow, read-only, at HEAD as of **2026-09-11**:

- `openai/codex` @ `fc948f8c473e5d11e780ffcf1fd7f812a2020932`
- `google-gemini/gemini-cli` @ HEAD (2026-09-11 clone)
- `Aider-AI/aider` @ HEAD (2026-09-11 clone)
- `sst/opencode` @ HEAD (2026-09-11 clone)

---

## Codex CLI (OpenAI) — researched, NOT built

**Where:** `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session-id>.jsonl`,
one file per session (confirmed by community write-ups; not independently
re-derived from the file-naming code in this pass, only from the record
schema).

**Record shape**, read directly from source:
- `codex-rs/history/src/lib.rs`: `RolloutLine { timestamp: String, ordinal:
  Option<u64>, #[serde(flatten)] item: RolloutItem }`.
- `RolloutItem` is a big enum — `SessionMeta`, `ResponseItem`,
  `InterAgentCommunication`, `InterAgentCommunicationMetadata`, `Compacted`,
  `TurnContext`, `TokenUsageRecord`, `WorldState`, `SecurityRiskScore`,
  `RetainedContext`, `EventMsg`, `RealtimeItem` — internally tagged
  (`#[serde(tag = "type", rename_all = "snake_case")]` on the wire type,
  `codex-rs/history/src/rollout_payload.rs::RolloutItemWire`).
- The turn payload for a real message is `RolloutItem::ResponseItem`, whose
  `payload` is `codex_protocol::models::ResponseItem::Message { id, role:
  String, content: Vec<ContentItem>, phase, ... }` (`codex-rs/protocol/src/
  models.rs`), `ContentItem` = `InputText | InputImage | InputAudio |
  OutputText` (each `{text}` for the text variants) — structurally very close
  to Claude Code's `message.content` block list.
- `SessionMeta` (`codex-rs/protocol/src/protocol.rs`) carries `session_id`,
  `id` (ThreadId), `forked_from_id`, `parent_thread_id`, `timestamp`, `cwd`.

**Why not built.** Two things pushed Codex below Gemini CLI on "best
verified":

1. **The schema is bleeding-edge and unstable at the commit I read.** This is
   not the simple `{session_meta, event_msg, response_item, turn_context,
   compacted}` shape that community write-ups from a few months earlier
   describe — the HEAD I cloned has grown `WorldState`, `SecurityRiskScore`,
   `RetainedContext`, a `Guardian` subsystem, and — separately from the
   rollout JSONL entirely — a SQLite-backed `thread-store` crate with its own
   migrations (`codex-rs/state/migrations/*.sql`) that appears to be taking
   over persistence for at least some record types. A real user's on-disk
   files depend heavily on which released version wrote them, and I have no
   way to tell, from source alone, which shape is what a `pip install`-able
   Codex CLI actually writes today versus what's mid-refactor on `main`.
2. **It does answer the `subagents/` question, and the answer is interesting
   enough to record even unbuilt.** Codex CLI has a real multi-agent
   subsystem (`spawn_agent` / `send_message` / `wait_agent` tools; see
   `codex-rs/history/src/lib.rs`'s `InterAgentCommunication` and
   `InterAgentCommunicationMetadata` rollout-item variants, and `ResponseItem
   ::AgentMessage { author, recipient, content }`). Unlike Claude Code, this
   traffic is **not** written to a separate file/directory — it is
   interleaved in the SAME rollout JSONL as distinct `RolloutItem` variants
   (`inter_agent_communication`, and `AgentMessage`-shaped `response_item`
   payloads, which are tagged distinctly from ordinary `Message` payloads).
   An adapter that only reads `RolloutItem::ResponseItem` payloads of kind
   `Message` (not `AgentMessage`) with `role` "user"/"assistant" would
   naturally skip agent-to-agent traffic by construction, without needing a
   Claude-Code-style directory filter at all — a third shape for the same
   question, after Claude Code's (path component) and Gemini CLI's (explicit
   field, see below).

**What would be needed to build this well:** a real `~/.codex/sessions` tree
from a released (not HEAD) version, or at minimum reading the tagged release
matching a specific PyPI/npm version, to pin down which `RolloutItem` variants
actually appear in the wild and confirm the `AgentMessage` tag name on the
wire (I read the Rust struct, not a serialized sample).

---

## Gemini CLI (Google) — researched and BUILT

Package `@google/gemini-cli-core`. Source read: `packages/core/src/services/
chatRecordingService.ts`, `chatRecordingTypes.ts`, `packages/core/src/utils/
sessionUtils.ts`, `environmentContext.ts`, `packages/core/src/config/
storage.ts`, `packages/core/src/core/client.ts`,
`coreToolHookTriggers.ts`.

**Where:** `~/.gemini/tmp/<projectHash>/chats/` — confirmed directly from
`Storage.getProjectTempDir()` / `Storage.getGlobalTempDir()`
(`config/storage.ts`: `GEMINI_DIR = '.gemini'`, temp dir is
`~/.gemini/tmp/<projectHash>`, `chatsDir = path.join(getProjectTempDir(),
'chats')`). One file per **main** session:
`session-<YYYY-MM-DDTHH-mm>-<sessionId8>.jsonl`.

**Record shape** (`chatRecordingTypes.ts`):
- First line of every file: a metadata record — `{sessionId, projectHash,
  startTime, lastUpdated, kind?, directories?, summary?, memoryScratchpad?}`
  (`PartialMetadataRecord`/the initial `ConversationRecord` fields), written
  by `chatRecordingService.ts`'s `initialize()` before anything else.
- Each turn after that: `BaseMessageRecord & ConversationRecordExtra` =
  `{id, timestamp, content, displayContent?, type: 'user'|'info'|'error'|
  'warning'|'gemini', ...type-specific fields}`. `content` is a
  `PartListUnion` (string, or `Part`/string array; a `Part` here is `{text}`
  or a non-text field like `functionCall`/`functionResponse`/`inlineData`).
- Two other record shapes can appear inline: `{$set: {...}}` (a metadata
  patch — `updateMetadata()`) and `{$rewindTo: <id>}` (an undo marker). Both
  are structural bookkeeping, not turns.
- `type: 'info'|'error'|'warning'` messages are UI-only feedback (slash
  command results, error banners) — same "not a turn by design" bucket as
  Claude Code's `tool_use`/`tool_result` records.

**The `subagents/` question, answered with a stronger signal than Claude
Code's.** Gemini CLI nests delegated-agent transcripts, but not under a fixed
literal directory name. `chatRecordingService.ts`, in the branch handling a
new session:

```ts
// subagents are nested under the complete parent session id
if (this.kind === 'subagent' && this.context.parentSessionId) {
  chatsDir = path.join(chatsDir, safeParentId);   // parent SESSION ID, not "subagents"
}
```

So a subagent's file lives at `chats/<parentSessionId>/<subSessionId>.jsonl` —
a directory named after a UUID/promptId, which is indistinguishable in shape
from any other path segment. **A Claude-Code-style directory-name filter
(`if "subagents" in path.parts`) would silently miss every one of these.**
The one reliable signal the format actually gives is explicit and typed: the
metadata record's own `kind: 'main' | 'subagent'` field
(`chatRecordingTypes.ts::ConversationRecord.kind` /
`PartialMetadataRecord.kind`). `corpuslens/ingest/gemini_cli.py` reads that
field, not the path, and skips the whole file (every record counted as a
drop) when it reads `subagent` — same outcome as the Claude Code fix, reached
by the one signal this runtime actually exposes. This is recorded as a
finding in the adapter's own docstring, matching BUGS.md's fixed entry.

**Injected wrapper tags found and added to `injection.py`** (both grep-located
to exact call sites, not inferred):
- `<session_context>` — `utils/environmentContext.ts::getEnvironmentContext()`
  builds a block with today's date, OS, the project temp dir, the directory
  tree, and session memory, and `getEnvironmentContextTurns()` inserts it as
  the session's very own **first `user` turn** (`role: 'user', parts: [{text:
  envContextString}]`) — this is Gemini CLI's version of the exact
  front-loading finding this project already made twice (Cursor's
  `<user_info>`, Claude Code's own harness). Left unfiltered it would inflate
  `opener_median_words` the same way.
- `<hook_context>` — `core/client.ts` and `core/coreToolHookTriggers.ts` both
  wrap external-hook output as `` `<hook_context>${additionalContext}
  </hook_context>` `` and inject it into a later user turn.
- Gemini CLI's OWN resume code already treats both as not-a-real-user-turn:
  `utils/sessionUtils.ts::isIgnoredUserContent()` special-cases
  `trimmedContent.startsWith('<session_context>')` and
  `startsWith('<hook_context>')`. That function also ignores content starting
  with `/` or `?` (slash commands, bare questions) — those are NOT added to
  `injection.py`, because they are still human-typed input, just structurally
  uninteresting to Gemini's own resume flow; corpus-lens's injection filter
  only strips machine-supplied text, and inventing a new "ignore short human
  input" rule not evidenced by any other adapter would be scope creep beyond
  what the source actually showed.

**What I verified vs. inferred.** Verified directly from source, cited by
file and symbol in `gemini_cli.py`'s docstring: the file path/naming rules,
the metadata-record-first-line rule, the message record's field names, the
`kind` field and its subagent semantics, and both injected tag strings with
their exact wrapper syntax. Inferred/assumed, disclosed in the docstring: (a)
that a file with no metadata record at all (truncated/corrupt) should be
processed as an ordinary session rather than guessed as a subagent — a policy
choice for a degenerate file, not a schema guess; (b) that `PartListUnion`
items lacking a `text` key never carry text worth extracting (matches every
other adapter's "extract only text blocks" convention, but I have no captured
`functionCall`/`functionResponse` JSON sample to confirm the exact key
spelling beyond the TypeScript type definitions in `packages/core/src/utils/
sessionUtils.ts` and `models.rs`-equivalent `@google/genai` types, which I did
not clone).

**What a real corpus would still need to confirm:** whether every installed
version in the wild actually writes this exact shape (the PR history shows
this JSONL format replaced an older single-JSON-per-session format —
`chatRecordingService.ts` still contains a migration path for `.json` legacy
files, which this adapter does not read, since it only walks `*.jsonl`); the
real distribution of `type` values seen in practice; and whether
`<session_context>`/`<hook_context>` are the only machine-injected wrappers,
or whether there are others this reading missed (e.g. IDE-context injection,
which the source references in passing via `ideContext`/tiered-context
comments in `environmentContext.ts` but which I did not fully trace).

---

## aider — researched, NOT built

**Where:** `.aider.chat.history.md` (configurable), plus separate files for
model metadata (`.aider.model.metadata.json`) and shell input history
(`.aider.input.history`) — unrelated to conversation content.

**Format, confirmed from source** (`aider/io.py`):
- `InputOutput.append_chat_history()` (line 1117) just appends raw text to a
  markdown file — `# aider chat started at <time>` is written once per
  session start (`aider/io.py:336`), and every subsequent turn is appended as
  markdown (blockquoted assistant text, etc.) with **no per-turn structured
  record and no per-turn timestamp** — only the one session-start line carries
  a clock.
- There is no `role` field, no JSON, no per-message id. Recovering "who said
  this" and "when" would require parsing markdown heading/blockquote
  conventions and would still leave every turn after the first with no
  timestamp at all — the same problem `cursor-store` already has for tool
  steps, but here it applies to literally every conversational turn.

**Why not built.** This is a fundamentally weaker corpus shape than the other
three: prose transcript, not structured turns; one clock reading per session,
not per turn. Building an adapter here would mean either (a) inventing a
tempo-free, role-inferred-from-markdown-structure adapter with a much larger
gap between "format is real" and "record shape is reliably recoverable" than
any adapter already in this project, or (b) reading `.aider.input.history`
(which does timestamp each line the user typed at the prompt, per aider's
`--input-history-file` handling) and correlating it by adjacency with the
markdown transcript — a correlation, not a read, and exactly the kind of
inference this project's rule forbids. Named unbuilt rather than built badly.

---

## opencode — researched, NOT built

**Where:** historically (per `ccusage`'s own opencode reader and multiple
community write-ups) `~/.local/share/opencode/storage/{session,message,part}/
...` as one JSON file per session/message. **This is no longer accurate for
the current source.**

**What the current source actually shows** (`packages/opencode/src/session/
session.ts`, `packages/opencode/src/storage/storage.ts`): the session index is
now backed by `drizzle-orm` against a SQL table (`SessionTable`, with columns
including `parent_id`), not flat per-session JSON files — `storage.ts`'s
generic `file()`/`read()`/`write()` layer still exists for other artifacts
(diffs, summaries) but session/message persistence appears to have moved onto
a relational store at HEAD. This is the same shape of problem Codex CLI has:
**the on-disk format is mid-migration**, so which shape a real user's data is
in depends on which version wrote it, and I have not identified an actual
`.sqlite` file path or schema-migration file to confirm the current DB
location/schema the way I did for Codex's `codex-rs/state/migrations/*.sql`.

**The `subagents/` question, partially answered.** `session.ts` has an
explicit `parentID` on session records (`children(parentID)`, `parentID:
input?.parentID` on session creation) — opencode sessions form a parent/child
tree, strongly suggesting subagent/sub-task sessions are child sessions of the
dispatching one. I did not trace far enough to confirm whether a child
session's messages ever get merged back into the parent's read path (which
would recreate exactly the corpus-lens bug) or whether `role` distinguishes
a sub-session's turns from a human's. This is a real gap, not a "no" — it is
"researched, inconclusive," and is named honestly as such rather than
guessed.

**Why not built.** Two independent reasons, either alone would have been
enough: the storage layer is mid-migration between flat JSON and SQL (so
"the format" is ambiguous without knowing which released version a user has),
and the `subagents/` question — the task's explicit precondition for shipping
an adapter — could not be answered with confidence in the time available.

---

## Doc changes needed (not made here — README.md/IDEAS.md are off-limits this pass)

- README.md: add `gemini-cli` to the adapters list/quickstart (`corpuslens run
  ~/.gemini/tmp --adapter gemini-cli`), and add a short "deliberately does not
  count as you" callout for Gemini CLI's `<session_context>` opener and its
  `kind:"subagent"` nesting, mirroring the existing Claude Code callout.
- README.md "Status: spine" adapter count (currently "five adapters") needs
  to become six.
- IDEAS.md's "More runtimes on the same seam" bullet should be updated to
  mark Gemini CLI done, and to fold in the Codex/aider/opencode findings above
  (bleeding-edge/mid-migration schemas, aider's prose-transcript shape) so the
  next person attempting Codex or opencode does not re-derive the same
  "format is currently in flux" finding from scratch.
- BUGS.md's fixed-bugs section could gain a short cross-reference noting the
  `subagents/` fix now has a second, differently-shaped instance (Gemini CLI's
  `kind` field vs. Claude Code's path component) — useful precedent for
  whoever builds the Codex or opencode adapter next, since neither of those
  will look like either existing case.

---

## Bottom line: the boundary between verified and inferred

**Verified against the runtime's own source, with file/line citations kept in
the adapter's docstring:** Gemini CLI's file location and naming, the JSONL
record shapes (metadata record, message record, `$set`/`$rewindTo`
bookkeeping), the `kind` field and its subagent semantics, and both injected
wrapper tags with their exact delimiter syntax and injection call sites.

**Not verified — inferred, or explicitly left open, and said so in the
adapter docstring and here:** whether every version of Gemini CLI a real user
might have installed writes this exact JSONL shape (a legacy single-JSON
format is referenced in the migration code path and is NOT read by this
adapter); the full set of machine-injected wrappers (only two were traced;
IDE-context injection was seen referenced but not followed to its source);
and, most importantly, **everything here is unconfirmed against a single byte
of a real Gemini CLI session log**, because none was available. Running this
adapter against one real `~/.gemini/tmp/*/chats/` tree and diffing its
`doctor` drop-share against zero would be the single most valuable next step
— exactly the same gap this project's own `claude_code.py` closed by being
run on its author's real corpus, which is not yet possible here.
