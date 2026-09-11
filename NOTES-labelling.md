# Notes for the README/IDEAS merge (`corpuslens label` / `corpuslens score`)

I did not edit `README.md` or `IDEAS.md` per instructions (parallel agents).
This is the exact set of sentences that need to change once this branch lands,
quoted old → new, so whoever reconciles the docs doesn't have to re-derive it.

## README.md

**Status: spine** section, the CLI list.

Old:
> CLI (`run`, `doctor`, `adapters`, `analyzers`), test suite (wall + pipeline +

New:
> CLI (`run`, `doctor`, `adapters`, `analyzers`, `label`, `score`), test suite
> (wall + pipeline + label + db-adapter + CLI-surface + render + regression
> tests for every review finding).

(The rest of that sentence — `db-adapter + CLI-surface + render + regression
tests...` — stays, just gains `label`; I put the new test file at
`tests/test_label.py`.)

No other README sentence describes the CLI surface closely enough to need a
change (the Quickstart section only demonstrates `run`), and none of the
wall's claims changed — `label`/`score` add no new absolute-time or content
leakage path; see "What I built" below for why.

## IDEAS.md

**"A local labelling mode" (Near)** — the entry this task implements. Three
sentences no longer describe what got built and should be corrected, not
just marked done:

1. Old:
   > `corpuslens label <path> --adapter …` samples fifty operator turns (a
   > fixed seed, so a run is repeatable), shows each one in the terminal, and
   > asks one yes/no per classifier — did this turn author code, refer to
   > code, deliberate, and, on a machine turn, ask a clarifying question.

   New (two corrections: the sample pools BOTH eligible operator prompts and
   eligible machine responses together — not "fifty operator turns" — because
   the clarify question needs machine turns to ever be asked; and the sample
   size is a `--sample-size` flag, default 50, not a hardcoded fifty):

   > `corpuslens label <path> --adapter …` samples up to 50 (`--sample-size`,
   > default 50) eligible turns — operator prompts and machine responses alike,
   > pooled together under a fixed seed so a run on the same corpus is
   > repeatable — shows each one in the terminal, and asks one yes/no per
   > classifier that applies to it: did the operator author code, refer to
   > code, or deliberate; did the machine ask a clarifying question.

2. Old:
   > A second run on the same corpus can then print precision and recall per
   > classifier against the labels, with `n`, and the report can carry those
   > numbers beside every headline percentage instead of the sentence "trust
   > direction plus your own spot-check".

   New (this is two separate claims; only the first is built):

   > A separate `corpuslens score` command re-runs the classifiers over the
   > same corpus and prints precision, recall and `n` per classifier against
   > the label store, with the same named-denominator discipline as the
   > analyzers. **Not yet done:** wiring those measured rates into `run`'s
   > report beside each headline percentage — the report still says "trust
   > direction plus your own spot-check" unconditionally. Doing that cleanly
   > needs `run` to accept a label-store path and decide what to show when no
   > store exists yet, which is its own small design, deliberately left open
   > here rather than bolted on.

   (I chose two verbs, `label` and `score`, over one command with a `--score`
   flag — matching this file's existing one-verb-per-subcommand shape
   (`run`/`doctor`/`adapters`/`analyzers`) rather than overloading either.
   Worth confirming that's the intended reading of "a second run" above, since
   the phrase is ambiguous between "rerun `label`" and "a second command".)

3. New sentence needed (a real, current limitation, not in the original spec
   text at all): interactive labelling needs the corpus's raw turn text to
   show a human, which the wall-respecting `ingest()` pipeline does not carry
   past feature extraction by design. I added a SEPARATE function,
   `label_text(path, ...) -> LabelCorpus`, registered per-adapter via
   `ingest.register_label_text` — not a keyword on `ingest()` itself, after a
   2026-09-11 audit finding that a flag changing one function's return arity
   is exactly the kind of seam a wall bug hides in. Only `claude-code`
   registers one (`ingest.text_capable_of`); `label` refuses loudly on
   `cursor`, `cursor-store`, `sqlite`, and `postgres` rather than guessing at
   each one's text-extraction shape. Add, after the paragraph above:

   > Today only the `claude-code` adapter supports `label` (it is the one
   > adapter that registers a `label_text` function to hand back a turn's
   > text for display) — every other adapter is refused outright rather than
   > guessed at. `corpuslens score`, which never needs turn text, works
   > against any adapter's Events. `label_text`'s own docstring
   > (`corpuslens/ingest/claude_code.py`) carries the full argument for why
   > handing back an opaque-hash-to-content map outside the Guard is allowed
   > here specifically, and the conditions under which that stops holding —
   > worth folding a compressed version of that into this IDEAS.md entry,
   > since it is exactly the kind of reasoning a future contributor would
   > otherwise have to reconstruct from the code alone.

4. The paragraph beginning "Constraints the reviewer named, kept" is still
   accurate as written — the labeller is the owner, the store is version-tied,
   and the sample-size argument stays in Stretch (I did not add anything
   resembling a power analysis; `--sample-size`'s help text says outright that
   50 is a convention, not a computed minimum). No change needed there.

**"Measuring the classifiers' own error" (Stretch)** — no change needed. The
2026-09-11 addendum already correctly describes what stays in Stretch (the
sample-size argument and per-classifier-per-corpus-type publication), and I
did not build either of those, so the addendum still holds.

## What was built against a guess, vs. against the real spec

None of it. The coordinator's correction (fetch + merge origin/main) arrived
before any code was written — only the branch existed. The design I had
already sketched from the compressed description in the task prompt matched
the merged IDEAS.md entry closely (fixed seed, `{source_ref, classifier,
label}` only, version-tied store, sample size as a stated convention), so no
part of the implementation had to be reworked after reading the real section
— but the fixed-seed sampling would have been "50 operator turns only" had I
guessed instead of read, since that is the merged doc's literal (slightly
loose) phrasing and I initially read it that way too before reconciling it
against the equally-explicit "on a machine turn, ask a clarifying question"
clause in the same paragraph, which only makes sense if machine turns are
sampled too.
