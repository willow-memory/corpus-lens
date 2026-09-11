"""Adapter: the Forge's checkpoint ledger (`forge-play/Forge`, `~/.forge`).

IDEAS.md ("Forge's own records", under Adapters) named this: the Forge's
checkpoint memory, calibration ledger and friction log are process records
of human+agent interaction — this tool's subject matter — and an adapter is
"roughly 100 lines on the existing seam". It is. What took longer than the
lines was deciding what those records honestly ARE, and this docstring is
mostly that.

## What the Forge writes, and which of it is a turn

The Forge (`forge/checkpoint.py`) puts a *decision* to a maker: a fork with
options, a keyword scan that left a major open, two writes to one path. The
maker answers; the answer is sealed into their own per-builder Nestor store;
the next time the same decision comes up, the engine confirms from memory
instead of asking. Every one of those steps lands in ONE hash-chained file,
Nestor's ledger, which the Forge points at `<FORGE_HOME>/checkpoints/ledger.jsonl`
(`forge/checkpoint_memory.py`). Read from a real run of the Forge's own
documented three-command loop, one checkpoint is these lines, in order:

    {"ts": "...", "kind": "entity_resolve", "domain": "builder:<id>:decision:<type>",
     "surface_sha": "...", "canonical": null, "sealed": false, "confidence": 0.0}
    {"ts": "...", "kind": "seal", "pair_id": "...", "verifier": "<id>", ...}
    {"ts": "...", "kind": "entity_seal", "domain": "...", "surface": "<the question>",
     "canonical": "<the answer>", "verifier": "<id>", "pair_id": "...", "surface_sha": "..."}
    {"ts": "...", "kind": "entity_resolve", "domain": "...", "surface_sha": "...",
     "canonical": "<the answer>", "sealed": true, "confidence": 1.0}

Three of those four are turn-shaped, and they map like this — the whole
adapter is this table:

| ledger line                          | who      | what it is                              | text            |
|--------------------------------------|----------|-----------------------------------------|-----------------|
| `entity_resolve` with `sealed=false` | machine  | the engine ASKED the maker a question   | `surface` (*)   |
| `entity_seal`                        | operator | the maker ANSWERED, and it was sealed   | `canonical`     |
| `entity_resolve` with `sealed=true`  | machine  | the engine CONFIRMED from memory, unasked | `canonical`   |

(*) An `entity_resolve` line carries no text, only `surface_sha`. The
question's text is on the `entity_seal` that answers it, so the adapter
joins the two by `surface_sha` within a file and gives the ask the
question it asked. An ask that was never answered (no `entity_seal` with
that hash anywhere in the file) has no text to featurize and is
dropped-and-counted, never given a placeholder. The `seal` line is the
same event as `entity_seal` seen from the store's side; it is dropped and
counted too, as is every other ledger kind (`reject_*`, `supersede`,
`attach_evidence`, ...) — they are not turns.

`domain` is the thread. `builder:<id>:decision:<type>` scopes one maker's
one decision type, which is what a checkpoint "session" is: the same
question coming back over days is a thread resuming. The builder id inside
it is a NAME, and it reaches an Event only as the opaque hash
`_rows.assemble` gives every session key — same as a db path, same as a
filename. The `verifier` field (also the builder's name), `pair_id`,
`origin` (which carries a project name) and `surface_sha` are read for the
join and then discarded; none of them is on an Event.

## What this corpus can and cannot measure — said up front

This is a corpus of checkpoints, not of conversation, and three analyzers
have nothing to measure in it. The adapter DECLARES them unmeasurable
rather than letting them run and report a plausible number:

- `steering_density` reads "where does your intent arrive — the opening
  prompt or mid-task?" A checkpoint has no opening prompt: every operator
  turn here is an answer to a question the engine asked, so every one is
  "mid-task" by construction and the rate is 100% with no content.
- `composition_mix` reads "who writes the code?" A maker's answer to a fork
  names an option ("exif in place"); it does not author code or cite it, so
  authored-code and code-reference shares are 0% with no content either.
- `clarification_pull` reads "how often does the machine ask?" — and that
  is the one number this corpus visibly holds: an `entity_resolve` with
  `sealed=false` IS the engine asking, `sealed=true` IS it confirming from
  memory, the Forge's own auto / recognize / socratic split. But the
  analyzer does not read the ledger; it reads the `clarify` feature, which
  `classifiers.CLARIFY` sets from an English phrase list built for chat
  ("do you mean", "should I", "which one"). A Forge question — *"'…' could
  be web, mobile, desktop — which major?"* — matches none of it, so the
  rate reads 0% however often the engine asked. Measured on the real demo
  ledger: 2 asks in 5 machine turns, reported as 0.0%. That is the
  undercount `classifiers.py` already discloses for other-language corpora,
  and the honest output is a refusal, not 0.0%. The split is a ledger fact
  a future change could carry as a ground-truth feature — but only with a
  disclosure on the result that the feature came from the record and not
  the classifier, which is a change to the analyzer's contract, not to
  this adapter.

All three are refused by name in the audit sentence (`refused:
steering_density (adapter forge: ...)`), and `corpuslens doctor` lists them,
so a reader who did not know what the corpus was cannot mistake a
structural zero for a finding. This is the `subagents/` bug (BUGS.md) and
the SWE-agent finding (IDEAS.md) taken at the adapter's door instead of
discovered afterwards: when a corpus cannot feed an analyzer, the honest
output is a refusal, not a number.

What IS measurable, and is the reason the adapter exists:

- `tempo` — within-day deltas between an ask and its answer: how long the
  maker took to answer a checkpoint. The Forge's engagement gate scores
  rubber-stamping; this is the same signal from the other end. (On a
  scripted run, such as the Forge's own demo, the answer follows the ask by
  milliseconds and the median reads 0.0s — which is true of that run.)
- `thread_shape` / `thread_span` — decision types resuming over relative
  days.
- `authorship_mix` / `signature_plurality` — whether the operator-role
  turns read as one human. The Forge's `human_attestations` carry a
  `by_human` flag that would be ground truth for that classifier; this
  adapter does not read it yet (IDEAS.md, "Measuring the classifiers' own
  error" — that is a labelling-mode question, not an ingest one).

## What it does not read

`<builder>.soil.json` (calibration predictions, attestations, the
human-required queue) and `<builder>.db` / `.schedule.json` are not read.
The predictions carry no clock, so they could only ever be dropped; the
attestations are the same seals as `entity_seal`, and reading both would
count each answer twice. If the Forge grows a record with a clock and a
text that is not already on the ledger, add it here with a row in the table
above — never by imputing a time.

Only in scope pointed at YOUR OWN builder id. A `~/.forge` with several
builders' checkpoints in it is a fleet's traffic, and IDEAS.md is explicit
that a fleet corpus is a different instrument with a different subject. The
adapter reads every ledger under the path it is given; scope it to your own
records the way you would any other corpus, and read `authorship_mix`'s
result before trusting a rate.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..model import Surface
from . import register, register_default_path, register_unmeasurable
from ._rows import assemble, as_text, parse_db_ts
from .drops import (DropCounts, EMPTY_TURN, MISSING_TIMESTAMP,
                    NOT_A_TURN_RECORD, UNPARSEABLE_LINE, UNREADABLE_FILE)

ADAPTER_ID = "forge/1"

#: The ledger kinds that are turns. Everything else is dropped and counted.
_ASK = "entity_resolve"
_ANSWER = "entity_seal"

UNMEASURABLE = {
    "steering_density": ("a checkpoint has no opening prompt; every operator turn is an "
                         "answer to a question the engine asked, so 'mid-task' is 100% by "
                         "construction and measures nothing"),
    "composition_mix": ("a maker's answer to a fork names an option; it neither authors "
                        "code nor cites it, so authored/read-ref shares are 0% by construction"),
    "clarification_pull": ("the CLARIFY phrase list was built for chat and a Forge question "
                           "('which major?') matches none of it, so the rate reads 0% however "
                           "often the engine asked; the ask/confirm split is on the ledger, "
                           "not in the classifier"),
}


def _lines(path: Path):
    """(lineno, record) for every parseable JSON object line; a bad line is
    yielded as (lineno, None) so the caller counts a drop, never a crash."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for n, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                yield n, None
                continue
            yield n, obj if isinstance(obj, dict) else None


def _read_ledger(path: Path, rel: str):
    """One ledger file -> (raw rows for `assemble`, DropCounts)."""
    records = [(n, r) for n, r in _lines(path)]
    drops = DropCounts()
    drops.add(UNPARSEABLE_LINE, sum(1 for _, r in records if r is None))
    # First pass: the question text each `surface_sha` was answered with.
    questions: dict = {}
    for _, r in records:
        if r and r.get("kind") == _ANSWER and r.get("surface_sha"):
            q = as_text(r.get("surface")).strip()
            if q:
                questions.setdefault(r["surface_sha"], q)
    raw = []
    for n, r in records:
        if r is None:
            continue
        kind = r.get("kind")
        domain = as_text(r.get("domain")).strip()
        d, epoch = parse_db_ts(r.get("ts"))
        if kind == _ASK and not r.get("sealed"):
            text = questions.get(r.get("surface_sha"), "")
            role = "machine"
        elif kind == _ASK and r.get("sealed"):
            text = as_text(r.get("canonical"))
            role = "machine"
        elif kind == _ANSWER:
            text = as_text(r.get("canonical"))
            role = "operator"
        else:
            drops.add(NOT_A_TURN_RECORD)  # `seal`, `reject_*`, `supersede`, ...: not turns
            continue
        if d is None:
            drops.add(MISSING_TIMESTAMP)
            continue
        if not domain:
            drops.add(UNPARSEABLE_LINE)   # no thread key — not a shape this adapter can use
            continue
        if not text.strip():
            drops.add(EMPTY_TURN)         # an ask never answered, or a blank canonical answer
            continue
        raw.append((d, epoch, domain, role, text, f"{rel}:{n}"))
    return raw, drops


@register_unmeasurable("forge", UNMEASURABLE)
@register_default_path("forge", "~/.forge")
@register("forge", source="dir", pattern="ledger.jsonl")
def ingest(path: str, corpus_id: str = "corpus"):
    root = Path(path).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"forge adapter expects a directory (e.g. ~/.forge), got {path}")
    raw = []
    drops = DropCounts()
    for f in sorted(root.rglob("ledger.jsonl")):
        rel = str(f.relative_to(root))
        try:
            rows, d = _read_ledger(f, rel)
        except OSError:
            drops.add(UNREADABLE_FILE)   # never abort the walk
            continue
        raw.extend(rows)
        drops.merge(d)
    events, quarantine, drops2 = assemble(raw, corpus_id, ADAPTER_ID, Surface.CLI)
    return events, quarantine, drops.merge(drops2)
