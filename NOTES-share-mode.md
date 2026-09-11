# NOTES: what README.md and IDEAS.md need after this branch

Written instead of editing README.md / IDEAS.md directly, per instructions
(seven agents working in parallel on those files). This lists every sentence
that is now stale, quoting the exact old text and the exact proposed new
text, so whoever reconciles the docs can apply these as literal edits.

Everything below assumes this branch's implementation:
`corpuslens/share.py` (the allowlist + `band_n`), `--share` on `corpuslens
run` (composes with `--format`, e.g. `--format json --share`), and
`SHARE_CAVEAT` in `corpuslens/render.py`.

---

## 1. README.md — remove "share-safe report" from the unbuilt list

**File:** `README.md`, in the "Named and deliberately unbuilt" list under
"Status: spine".

**Old text:**

```
- A local labelling mode, a share-safe report, and a corpus-type refusal are
  the next things in IDEAS.md's near list; none exists yet, and the report says
  "trust direction plus your own spot-check" until the first one does.
```

**New text:**

```
- A local labelling mode and a corpus-type refusal are the next things in
  IDEAS.md's near list; neither exists yet, and the report says "trust
  direction plus your own spot-check" until the first one does. A share-safe
  report now exists (`corpuslens run ... --share`, or `--format json
  --share`) — see "Share mode" below; it coarsens, it does not anonymize, and
  it does not answer whether a coarsened report can still re-identify its
  owner (see IDEAS.md, "Population reference points without pooling anyone's
  corpus").
```

Reasoning: the current sentence flatly says "none exists yet," which becomes
false the moment this branch merges — leaving it would be exactly the kind of
overclaim-by-omission this project's own rule (CONTRIBUTING.md, "never
overclaim") also forbids in the *stale-negative* direction, not just the
inflated-positive one.

---

## 2. README.md — document `--share` where `--format json` is documented

**File:** `README.md`, immediately after the `--since-day` / `--until-day`
paragraph in "### JSON output, and analyzing a slice" (the paragraph ending
"...those are subset numbers, not corpus numbers, and the report says that in
words.").

**New text to insert (new subsection, no old text to replace — this is an
addition):**

```
### Share mode

```bash
corpuslens run ./corpus --adapter claude-code --share
corpuslens run ./corpus --adapter claude-code --format json --share
```

`--share` is a modifier on `run`, not a third `--format` — it composes with
either renderer, because a machine consumer wants `--format json --share`
exactly as much as a person wants the coarsened markdown. It emits headline
rates only, to one decimal, with each denominator's `n` rounded to a wide
band (`<30`, `30-100`, `100-1000`, ...) instead of an exact count, and it
omits tempo quantiles, thread counts, day spans, concurrency figures and
active-day counts entirely — not rounded, not present. An analyzer that has
no field meeting that bar says so in words rather than showing an empty
section. The audit sentence still leads the report, and share output goes
through the same fail-closed egress scan as everything else.

**This output is coarsened. It is not anonymous, not de-identified, and not
a determination that it is safe to publish** — whether a coarsened report
can still re-identify its owner is exactly the open question IDEAS.md poses
in "Population reference points without pooling anyone's corpus," and this
feature does not answer it. It is the first output this tool produces that
is *meant* to leave the machine; treat "meant to leave" and "safe to leave"
as two different claims, because this tool only makes the first one.

The field-by-field rule: a value survives coarsening only if its name is on
an explicit allowlist in `corpuslens/share.py`, reviewed one field at a
time — an analyzer's new field is, by construction, not on a list written
before it existed, so it is withheld by default rather than shown by
default.
```

---

## 3. README.md — mention share mode in the "Built" line

**File:** `README.md`, "Status: spine" section.

**Old text:**

```
Built: event model, the wall, five adapters (claude-code, cursor, cursor-store,
sqlite, postgres), injection filter, six analyzers, markdown + JSON renderers,
CLI (`run`, `doctor`, `adapters`, `analyzers`), test suite (wall + pipeline +
db-adapter + CLI-surface + render + regression tests for every review finding).
```

**New text:**

```
Built: event model, the wall, five adapters (claude-code, cursor, cursor-store,
sqlite, postgres), injection filter, six analyzers, markdown + JSON renderers,
a share mode (`--share`, allowlist-coarsened, composes with `--format`), CLI
(`run`, `doctor`, `adapters`, `analyzers`), test suite (wall + pipeline +
db-adapter + CLI-surface + render + share + regression tests for every review
finding).
```

---

## 4. IDEAS.md — mark "A share mode for the report" built

**File:** `IDEAS.md`, end of the "### A share mode for the report" entry
(after the paragraph ending "...it just makes the object the question is
about exist.", before "### Say whose corpus the reference is").

**Old text (the entry's last paragraph, for anchoring — unchanged):**

```
Two things it does that nothing else here does. It gives people a way to talk
about their numbers in public without the fingerprint — the first time the tool
has an output that is *meant* to leave the machine. And it is the concrete
first step toward [Population reference points](#population-reference-points-without-pooling-anyones-corpus):
that entry's open question is what a contribution narrower than the report
would look like, and this is a candidate, built and inspectable before anyone
proposes pooling it. It does not answer the re-identification question that
entry asks; it just makes the object the question is about exist.
```

**New text to append right after it (mirrors the dated-update style already
used under "Measuring the classifiers' own error"):**

```

*2026-09-11: built.* `corpuslens/share.py` implements this as a field-name
allowlist (`RATE_FIELDS`) reviewed one field at a time, plus `band_n` for the
denominator band — not a blocklist over the shapes named above, because a
blocklist has to know about a leak in advance and an allowlist does not: a
new analyzer's new field is absent from a list written before the analyzer
existed, so it is excluded by construction rather than by someone
remembering to add it to a "don't show this" list. `--share` composes with
`--format` (`--format json --share`) rather than being its own format. Two
fields left off the allowlist despite looking like plain rates —
`single_turn_sessions_pct`, `single_day_threads_pct` — and two more excluded
as timing-shape rather than timing-coverage — `burst_pct`, `resumed_pct` on
`tempo` — are judgment calls, not settled ones; a future contributor may
reasonably disagree and should say why in the same place this note does. The
underlying question this entry opened — whether ANY report, however
coarsened, is safe at cohort scale — is still open; see "Population reference
points without pooling anyone's corpus" below, unchanged by this.
```

---

## Judgment calls a doc reconciler should know about (not just typos)

- **`burst_pct` / `resumed_pct` (tempo) were excluded**, even though IDEAS.md's
  own sentence ("no tempo quantiles ... at all") only names quantiles by name.
  They are a two-bucket histogram of the same censored inter-turn gaps that
  produce the quantiles — bucketing a timing distribution two ways instead of
  four does not stop it from being a timing distribution, and the task's own
  instruction ("when in doubt, omit it") points the same direction. Worth a
  second opinion rather than treating it as settled.
- **`delta_coverage_pct` (tempo) was kept.** It reports what fraction of
  turns have a measurable gap AT ALL, not what the gaps are — no shape of the
  gap distribution leaks through it, so it reads as a plain rate.
- **`single_turn_sessions_pct` and `single_day_threads_pct` were excluded**
  despite ending in `_pct`: both describe the shape of a distribution (how
  many sessions/threads are exactly one unit long), which is exactly the kind
  of thing "when in doubt, omit" is for.
