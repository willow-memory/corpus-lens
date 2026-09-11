# Design: extracting the Guard as a reusable mechanism

Status: **design only — no split performed.** IDEAS.md ("Publish the wall as a
reusable mechanism," under "Further out, and harder") says extraction is **not
first**, because the Guard has exactly one caller today and splitting an
interface that has never been exercised by a second one freezes guesses as
API. This document does the design work that decision explicitly defers,
so that when a second caller exists the split is a known quantity rather than
a fresh investigation. It changes nothing in `corpuslens/`.

Everything below is reasoned from `guard.py`, `model.py`, `cli.py`,
`render.py`, `tests/test_wall.py`, and the IDEAS.md text for the three
near-term callers the "Sequencing" paragraph under "Publish the wall as a
reusable mechanism" names by name — **A share mode for the report**, **A local
labelling mode**, and **The leakage demonstration — the one analyzer for the
quarantined class** — as specified in the 2026-09-11 review pass folded into
IDEAS.md. None of those three exist as code yet in this checkout; agents are
building them in parallel, so this reasons from the IDEAS.md specifications,
not from their eventual implementations.

**A note on process, since it matters for how much to trust §2 below:** this
document's first draft was written against a checkout that had the "Publish
the wall as a reusable mechanism" entry *without* its "Sequencing" paragraph —
the paragraph naming the three callers and the "not first" judgment did not
exist in that checkout yet, because it landed on `origin/main` after this
worktree was created. That first draft of §2 was written from an educated
guess at what "share mode," "labelling mode," and "leakage demonstration"
would mean, cross-referencing the `leakage_demonstration` claim type already
present in `model.py` and the "Population reference points" and "Measuring
the classifiers' own error" Stretch entries. After being told the worktree
was behind, `git fetch origin main && git merge origin/main` was run before
finishing this document, and §2 below is written fresh against the real
specification text (`A share mode for the report`, `A local labelling mode`,
and `The leakage demonstration`, all under "Near" or "Further out" in the
merged IDEAS.md). The guess and the real spec diverged in one significant
way, on the leakage demonstration specifically — noted inline in §2c, because
the divergence itself is informative about how easy this interface is to get
wrong from a name alone.

---

## 1. What the mechanism actually is, vs. what corpuslens happens to need

Reading `guard.py` line by line, four things are genuinely general — they
would make sense in a library with no idea what an "analyzer" or a
"Quarantine" is — and three things are corpuslens-specific, wired to this
project's exact vocabulary.

### General mechanism (survives extraction unchanged in spirit)

- **Capability gating with a fail-closed default.** `Profile.grants()`,
  `KNOWN_CAPABILITIES`, and the "absence of policy is denial" branch in
  `release()` are a generic pattern: a named, closed set of capabilities, a
  profile that defaults to none of them, and an unknown capability treated
  identically to a denied one. Nothing here mentions dates or filenames by
  necessity — it happens to gate `calendar_time` and `local_tz`, but the
  *shape* — "you may not read field X of the quarantine without an explicit
  grant plus a non-empty justification plus (for some capabilities) an owner
  token" — is domain-free.
- **Fail-closed release with a justification requirement and an escalated
  tier ("owner token").** The idea that some capabilities need more than a
  grant — they need a *proof of standing* separate from the grant itself — is
  general. `owner_token` is corpuslens's name for "prove you are the subject,
  not just someone who edited a profile," which is a real and reusable
  distinction (a grant says "this code path is allowed to ask"; a token says
  "and the person running it is the one entitled to know").
- **The egress scan as a backstop, not a source of truth.** `scan_egress`'s
  design — re-scan the *rendered output* for the literal quarantined values,
  and only forbid a value class whose capability was **not** released this
  run — is a generic defense-in-depth idea: upstream discipline can fail
  (a new field slips onto a result object, an analyzer serializes something it
  shouldn't), and a text-level backstop at the one choke point every output
  must pass through catches that class of bug without knowing anything about
  *why* the value is sensitive.
- **The audit sentence as a first-class object, not a log line.** Emitting a
  structured `AuditRecord` *and* a plain-language sentence derived from it,
  and refusing to let a "machine-readable" JSON output skip the sentence
  (`render.py`'s explicit comment on this), is general: any system that
  releases something-normally-withheld should say so in one sentence a
  non-engineer can read, attached to the very payload that used the release.

### Corpus-specific (would need to move to, or be reimplemented by, the caller)

- **The claim-type allowlists.** `PROCESS_CLAIM_TYPES` / `PERSON_CLAIM_TYPES`
  in `model.py`, and `Guard.admit()`'s walk over `analyzer.claims`, encode
  corpuslens's specific ontology (`steering_density`, `thread_shape`,
  `life_partition`, …). A generic library has no opinion on what a "claim
  type" is for a *different* domain (e.g., a clinical de-identification tool
  gating "diagnosis code" vs. "free-text note"). The *mechanism* — "a
  declared output type must be on an allowlist, and declaring an off-list type
  is a registration-time refusal" — is general (see §3); the *allowlist
  contents* are corpuslens's alone.
- **`Quarantine`'s field names.** `base_date_iso`, `local_tz`, `ref_map` are
  corpuslens's three quarantined values. `release()` and `scan_egress()` both
  hard-code these three names and, worse, hard-code *which capability governs
  which field* (`cap == "calendar_time"` returns `self.__q.base_date_iso`
  by name). A library's Guard cannot know a caller's field names in advance.
- **The analyzer `admit` path.** `admit(analyzer)` assumes a specific object
  shape (`analyzer.claims`, `analyzer.name`) and a specific two-tier claim
  ontology (process vs. person). This is corpuslens's registration contract,
  not a general "may this computation run" predicate.

The dividing line, stated as a rule: **anything that reasons about *policy
shape* (is a capability granted? does an unreleased value still appear in the
output? what sentence do we owe the reader?) is the mechanism. Anything that
reasons about *this project's specific fields and claim vocabulary* is the
integration.** Today those two things live in the same 229-line file with no
seam between them — `release()`'s body is half generic dispatch, half
`if cap == "calendar_time": return self.__q.base_date_iso`.

---

## 2. The interface a second caller would need

Working through each of the three callers the "Sequencing" paragraph names —
quoting IDEAS.md's own spec for each, not a guess — against today's actual
method signatures (`release(cap, justification)`,
`resolve_ref(opaque_ref, justification)`, `scan_egress(text)`,
`admit(analyzer)`). None of the three exist as code in this checkout; agents
are building them in parallel, so this reasons from the specification
sections IDEAS.md now carries (**A share mode for the report**, **A local
labelling mode**, **The leakage demonstration**), not from their eventual
implementations.

### 2a. Share mode ("A share mode for the report")

The spec: `--format share` (or `--share` on the existing renderers) "emits a
coarsened report: the headline rates only, to one decimal, with each
denominator's `n` rounded to a band (`"30–100"`, `"100–1000"`), and **no**
tempo quantiles, thread counts, day spans or concurrency figures at all." The
audit sentence stays. It "goes through `scan_egress` like everything else."
IDEAS.md is explicit that this is deliberately the first output *meant* to
leave the machine, and a candidate first step toward "Population reference
points" — without itself answering that entry's re-identification question.

Where today's interface fits, almost exactly: `scan_egress(text)` already
operates on rendered text with no opinion on which renderer produced it, so a
third renderer (`render.share`, alongside `markdown` and `json_report`)
calling `guard.scan_egress(report)` before the CLI prints or writes it needs
no change to `Guard` at all. Of the three callers, this is the one whose
*egress* half needs nothing new — the coarsening (dropping tempo quantiles,
banding `n`) is renderer-layer work, not Guard work, and the wall's job here
is exactly the job it already does for `markdown`/`json`.

Where it is not quite free, on closer reading: `scan_egress` forbids literal
quarantined *strings* (the calendar anchor, a real filename, the timezone
string) that were not released this run — it has no concept of "this
*number* is too identifying to leave, even though it is not a quarantined
literal." A share-mode report with no calendar anchor and no filenames passes
`scan_egress` trivially even if the coarsening step upstream (in the
renderer) forgot to band an `n` or accidentally left a tempo quantile in —
`scan_egress`'s literal-string check cannot see that kind of leak, because
banding-and-dropping is a *content-shape* rule share mode owns, not a
quarantined-literal rule the Guard was built to enforce. **The interface
point worth carrying forward:** `scan_egress` is real defense-in-depth for
the anchor/timezone/filename class it was built for, but a second caller
should not read "goes through `scan_egress`" as "the Guard verifies the
coarsening is correct" — it verifies a narrower, adjacent thing. If a
library's Guard wants to make a stronger promise about a *coarsened* export
specifically, it needs a second, distinct check (e.g. a schema/shape
assertion on the share payload) that the current single-purpose
`scan_egress` was never designed to be.

**Audit note, added after this document's first review (not this analysis's
own finding — recorded here so a later reader can tell the two apart).**
Share mode has since been built inside corpuslens and audited. Both
predictions above held, the second one sharply: the coarsening step touches
the Guard nowhere, confirming that share mode needs essentially nothing new
from it; and the first implementation banded every analyzer's denominator
correctly but then published the exact corpus size through the audit record
anyway, passing `scan_egress` cleanly the entire time — because an exact `n`
in `AuditRecord.n_events` is not a quarantined literal `scan_egress` was ever
built to catch. That is a real, built instance of exactly the gap named
above, not a hypothetical: "goes through `scan_egress`" caught none of it,
because the leak was a *number the coarsening step forgot to also apply to*,
which is precisely the class of leak a literal-string scan cannot see by
construction.

### 2b. Labelling mode ("A local labelling mode")

The spec, quoted: `corpuslens label <path> --adapter …` "samples fifty
operator turns (a fixed seed, so a run is repeatable), shows each one in the
terminal, and asks one yes/no per classifier... It persists **only** the
label and an opaque hash of the turn — the same `source_ref` hash the `Event`
already carries — never content, never a filename, never a timestamp." A
label set is tied to the classifier version that graded it.

Where today's interface fits: the *persisted* half is naturally opaque
already — `source_ref` is already the hashed identifier `Event` carries, so
"persist only the label and this hash" needs nothing from `Guard` beyond what
every `Event` already exposes. This is the cleanest-fitting requirement of
the three, and arguably needs no Guard change to get the *write* right, only
discipline in the new `label` subcommand's own code.

Where it does not fit: to "show each one in the terminal," the command must
read the turn's actual **text** — something no `Event` carries (per
`model.py`: "the Event does not carry content") and something `Guard`'s only
content-adjacent method, `resolve_ref`, does not provide either: it returns a
`"filename:line"` locator, not the text at that location. So labelling mode's
terminal display must either (a) re-open the original source file/row itself,
using the locator `resolve_ref` reveals, entirely outside the Guard's view —
a second, ungated read path with no audit trail and no fail-closed behavior
of its own — or (b) the Guard gains a genuine content-reveal primitive (e.g.
`reveal(opaque_ref, justification) -> str`, gated exactly like `resolve_ref`)
that owns the read and can therefore audit it. Path (a) is what today's
`Guard` actually forces, since it has no such method; it means the single
biggest content-handling event in the whole tool (showing an operator their
own raw turn text, fifty times) currently has **no Guard involvement
whatsoever** — the Guard's remit stops at "here is where the text lives," not
"here is the text." A library serious about being the seam a labelling-style
feature leans on would need to decide, explicitly, whether reading content
is in scope for the Guard at all, rather than leaving it as a gap nobody
designed.

### 2c. Leakage demonstration ("The leakage demonstration — the one analyzer
for the quarantined class")

**This is the caller where the first draft of this document, written before
the "Sequencing" paragraph was available, guessed wrong in a way worth
recording rather than quietly correcting.** The guess (reasoning only from
the `leakage_demonstration` claim type in `model.py`) was that this would be
an ordinary registered analyzer — `run(events) -> dict` — that additionally
asks the Guard for a capability from *inside* `run()`, operating on the
corpus's own ingested `Event`s. The real spec is a different shape entirely.

The actual spec: `corpuslens fingerprint <file>` "takes **any** timestamped
export the owner holds — another tool's JSON dump, a calendar export, a sync
log, this tool's own quarantine if the owner grants it — and reports only how
re-identifying its timing shape is." It "never prints the schedule, never a
weekday label, never an hour" — only whether a weekly pattern is present, how
concentrated the hour-of-week histogram is, and roughly how many bits of
schedule the file carries. IDEAS.md calls it "the first analyzer that needs a
capability" and says it "runs under a non-default profile... on purpose, with
no CLI flag," and flags, as an explicitly open design question, "whether
`fingerprint` gets to be the one command that constructs such a profile
itself (it reads a file the owner names, not the corpus, and it emits no
anchored value)."

Two structural facts follow that the guessed version above did not surface,
and both matter more to the interface question than the guess did:

1. **Its input is not the corpus's `Event`s or `Quarantine` at all — it is an
   arbitrary file the owner names on the command line.** There is no
   ingest step, no `Quarantine` object, no `ref_map`. This is not "an
   analyzer requesting a capability from inside `run(events)`" — it is a
   wholly different kind of Guard client, one gating access to a resource
   (absolute timestamps in a file the *owner* points at, not the pipeline's
   own quarantine) that the current `Guard.__init__(self, quarantine, ...)`
   has no way to represent, because it is built around exactly one
   `Quarantine` instance with exactly three named fields belonging to *this
   corpus's* ingest. A library's Guard, to serve this caller, needs
   capability-gating decoupled from "the one quarantine object this Guard
   happens to hold" — closer to "a Profile that can gate an arbitrary
   caller-supplied resource," which today's `release()` (hard-wired to
   `self.__q.base_date_iso` / `self.__q.local_tz` by capability name) cannot
   do.
2. **It plausibly is not "an analyzer" in the registry sense at all.**
   `Analyzer.run(events) -> dict`, registered via `analyze/__init__.py`'s
   `register()` and iterated by `cli.run()`'s `for a in all_analyzers()`
   loop, assumes every analyzer receives the same `Event` list from the same
   ingest. `fingerprint` takes a *different* positional argument (a file
   path chosen per-invocation) and is described alongside `run`/`doctor`
   in IDEAS.md's prose the way a fourth top-level verb would be, not the way
   a battery member is. If that holds, "the first analyzer to request a
   capability" (this task's own framing, and this document's first-draft
   guess) is the wrong mental model twice over: it may not be in the
   analyzer registry, and what it requests a capability *for* is not
   something `admit()`'s claim-vs-capability split (§1) was built to reason
   about at all — `admit()` gates whether a registered analyzer's *declared
   claim types* are representable; `fingerprint` needs a capability gate on
   an *arbitrary external input*, a completely different resource class than
   anything `KNOWN_CAPABILITIES` names today.

The open design question IDEAS.md itself flags is the sharpest interface
question of the whole document: **does invoking `corpuslens fingerprint
<file>` on the command line count as "a CLI flag to grant capabilities"?**
`cli.py`'s own docstring states, as a load-bearing design claim, "there is
deliberately no CLI flag to grant capabilities — a grant is an owner-side
code change... not a switch someone can flip in a command line they found in
a README." If `fingerprint` constructs its own non-default `Profile`
internally so that a bare `corpuslens fingerprint some_export.json` "just
works" from a copy-pasted command line, that sentence in `cli.py` becomes
false the moment `fingerprint` ships — the whole subcommand *is* such a
switch, just spelled as a verb instead of a flag. Resolving this is a
prerequisite to building the feature at all, not a detail to settle
afterward, and it belongs squarely in Guard-interface design: a library
`Guard` should have an opinion on whether "a Profile that grants itself,
constructed by code the CLI ships and any user can invoke," is a `Profile`
at all, or a different, more restricted thing (e.g. a `Profile` variant that
can only ever gate an out-of-band file the owner names on that exact
invocation, never the corpus's own quarantine, so that "no CLI flag grants
access to *your session logs*" survives even if a narrower capability for
*named external files* does not).

### What the three callers say about the interface, together

| Caller | Wants | Today's gap |
|---|---|---|
| Share mode | egress checking of a *coarsened, banded* payload | `scan_egress` verifies quarantined literals are absent, not that coarsening/banding was done correctly — real, but narrower, defense-in-depth than "goes through the wall" suggests |
| Labelling mode | showing the owner their own raw turn **content**, safely | no content-reveal primitive exists; `resolve_ref` returns a locator, and the actual read happens entirely outside the Guard's view today |
| Leakage demonstration | gating access to an **arbitrary external file's** absolute timestamps, not the corpus's own `Quarantine` | `Guard` is built around exactly one `Quarantine` instance with three named fields; there is no capability-gating primitive for a caller-supplied resource, and the CLI-invocation-as-implicit-grant question is unresolved even in the spec |

None of these are exotic, and only one of the three (leakage demonstration)
turned out to be as structurally different from today's Guard as the first
draft feared — but it is different in a *sharper* way than guessed: not "an
analyzer that also touches the Guard," but a client that needs the Guard
mechanism generalized past "gates one corpus's one quarantine object" to
"gates an arbitrary named resource," plus an unresolved policy question about
what "no CLI flag" actually has to mean once a command exists whose entire
job is to construct a non-default profile. A library's Guard needs a richer
object lifecycle than "construct once from one quarantine, use three ways,
discard" — but which richer shape depends on how that CLI-invocation
question gets answered, which is exactly the kind of thing IDEAS.md's
"not first" judgment is protecting against deciding prematurely.

---

## 3. What a library must promise more carefully than `guard.py` does today

This is the most important section. IDEAS.md's own words: "a library gets
used by people who did not read `guard.py`." Today, every honest limit in
this codebase lives in three places: the module docstring at the top of
`guard.py`, the README's "The wall" section, and `tests/test_wall.py`'s
`HonestBoundaryTests`. All three are prose or test code — none of them is
something a caller is *forced* to encounter by using the API. A caller can
`import guard; g = Guard(q); g.release(...)` without ever reading the
docstring, and nothing in the type signatures stops them from believing
things the code does not support.

Walking each disclosed limit to the question "what would make a
signature-only reader unable to hold a false belief":

### 3.1 "The default profile grants nothing" — currently true by convention, not by type

Today: `Profile()` with no arguments happens to default every field to the
empty/None state. Nothing stops a caller from writing
`Profile(capabilities=frozenset({"calendar_time"}))` at the top of their
`main()` out of habit ("just in case"), and now every run of their program
is non-default with no CLI trace of it (corpuslens's own README brags "there
is deliberately no CLI flag to grant capabilities — a grant is an owner-side
code change," but that only holds because corpuslens's own `cli.py` hard-codes
`DEFAULT_PROFILE`; a library cannot enforce that its caller does the same).

**What would have to change:** the "no CLI flag" discipline is a
*policy about how the library is invoked*, and a library cannot enforce it in
someone else's `main()`. What it *can* do is make the ungranted case
impossible to get by accident and the granted case impossible to get quietly:
- `Profile` construction that requires **naming every granted capability
  explicitly and individually**, already true today (`frozenset`), is fine —
  keep it — but the library should ship a named, exported
  `Guard.default()` / `NOTHING_GRANTED` constant so "give me the safe one" is
  a one-token import, not "remember to not pass arguments."
- The library cannot stop a *host application* from wiring a non-default
  profile to a flag or a button a user can reach — it can only make sure that
  choice is visible in the audit sentence every time (§3.5), and it should
  say so explicitly in its own docs, rather than implying the "no CLI flag"
  discipline is a library guarantee rather than a corpuslens-specific policy
  choice about its *own* CLI. §2c's `fingerprint` question is the sharpest
  version of this: a subcommand whose entire purpose is to construct a
  non-default profile is functionally a CLI flag wearing a verb's name, and
  a library cannot detect or prevent that pattern in a caller — it can only
  refuse to make constructing a non-default `Profile` look like anything
  other than a deliberate, individually-named act (per the bullet above),
  so at least the *caller's own source* has a code change to point at, even
  if a user copy-pasting a command line never sees it.

### 3.2 Weekly cadence is not hidden — this has to be a **type-level fact about the released data**, not a caveat about the mechanism

Today: this is true about `CoarseTime.day_offset`, which a signature reader
sees as `int` with no hint that `day_offset % 7` is a semi-identifying
quantity. Nothing in the *type* says "this int carries a weak periodic
signal"; you have to have read the module docstring or the README.

**What would have to change:** a library cannot stop `day_offset` from
preserving cadence — that's mathematically inherent to relative-day data, as
the README says outright, and no API design fixes that. What it *can* do is
stop the type from looking innocent. Two concrete moves:
- Name the type so the limit is unavoidable at the call site — not
  `CoarseTime` (neutral-sounding) but something the docstring-avoiding
  reader still trips over, e.g. a class-level docstring is not enough, but a
  **required, non-defaulted field that states the caveat as data** would be:
  a `cadence_disclosed: bool = True` field is silly, but a real move is
  exposing a `.weekly_cadence_reconstructable` **classmethod or module-level
  constant that is `True` and cannot be set `False`** — so a caller who
  writes an integration test asserting the library's own disclosed
  properties (as `test_wall.py` does today, informally) has something to
  assert against that isn't prose. This turns "read the docstring" into
  "read the one constant the docstring points at, which the test suite
  pins."
- More importantly: **the library's own audit sentence (see 3.4) must
  mention cadence on every single release, unconditionally** — not just in
  the granted branch. Today's `AuditRecord.sentence()` DOES do this in the
  ungranted branch ("these preserve weekly cadence...") — that discipline
  is exactly right and should be the thing that survives extraction *as a
  hard requirement of the sentence-building code*, not an editorial choice
  someone could drop from a future edit. Concretely: make the "does not hide
  weekly cadence" clause a piece of a sentence template the library owns and
  the caller cannot suppress, not a string literal a maintainer typed into
  `guard.py` this one time.

### 3.3 Within-day time-of-day is only loosely bounded — needs a **return type that cannot be mistaken for a clean value**

Today: within-day `delta_prev_s` is a plain `Optional[float]`. Nothing marks
it as "this, accumulated across a long thread, loosely bounds local
time-of-day" — a caller doing their own cumulative-span analysis on top of
the library's output (exactly the thing corpuslens's own `tempo` analyzer
*deliberately does not do*, per the README: "It deliberately publishes no
*cumulative* within-day span") gets a bare float with no signal that summing
it is exactly the operation the original project chose to withhold.

**What would have to change:** this is the sharpest case in the whole
document, because the dangerous operation (summing deltas within a day) is
something a *plain float* invites and nothing in the type stops. A library
serious about this promise should not return a raw `float` for
`delta_prev_s` at all — it should return a small value type (e.g. a
`WithinDayDelta` wrapper) whose docstring states the bound risk, and,
more forcefully, the library should consider **not exposing per-event deltas
at all as a public return type**, only pre-aggregated statistics that the
library itself computes with the cumulative-span risk already accounted for
(median, quartiles, share-with-no-delta — exactly what corpuslens's `tempo`
analyzer already reports, and exactly the boundary corpuslens draws around
publishing a cumulative span). In other words: **the safest interface is one
where the caller cannot even construct the summation that produces the
leak**, because a docstring on a float does not stop `sum(d.delta_prev_s for
d in day_events)`.

### 3.4 "Not an adversarial sandbox against the owner" — must be an **exception type and a doc-comment on `release()`, not an assumption**

Today: this is arguably the limit best-handled by the *existing* design —
`Guard.__q` is merely name-mangled, not actually inaccessible
(`self._Guard__q` reaches it from outside the class), and the module
docstring says outright that this is by design: "not, and does not claim to
be, unbypassable by the owner." That honesty is good. But a library user who
has not read the docstring will reasonably assume `__q` means "private,"
i.e. *enforced*, because that is the overwhelmingly common meaning of a
double-underscore attribute in Python code they've seen elsewhere — the
signature *actively misleads* here, name-mangling being the closest thing
Python has to a "keep out" sign, deployed for a thing the project explicitly
does NOT want to keep out the one party (the owner) most likely to look.

**What would have to change, revised after review.** This document's first
draft offered two options here — rename to a single underscore, or go the
other way and remove the dot-path entirely (store the quarantine only as a
closure the class captures, so there is "genuinely no dot-path to it without
calling `release()`"). On review, the second option was rejected, correctly,
and the reasoning is worth keeping rather than just the verdict: `guard.py`
does not merely concede that the owner can reach their own data as an
unfortunate side effect — it states the position affirmatively, three times
in the same docstring ("not an adversarial sandbox against the machine's
OWNER"; "a determined owner can always read their own quarantined data by
editing their own script"; claiming otherwise "would itself be the overclaim
this project forbids"). Removing the dot-path makes the owner's access
*harder* while leaving it *possible* (a determined owner can still
monkey-patch `release()` itself, as the first draft already noted) — which
buys no real protection against anyone the wall is actually meant to stop,
and spends effort moving the mechanism's outward posture a step toward the
sandbox the project has committed, in writing, to not being. A design choice
that makes a system *look* more locked down than its own documentation says
it is is the same overclaim risk as §3.1–§3.3, aimed at the code's own
shape instead of its docs. **The one path forward is the rename:** `__q`
becomes a single-underscore `_quarantine` — conventionally "internal, but
reachable, at your own risk," which is the true state of affairs — so the
naming convention stops promising an enforcement the project has never
wanted and does not deliver. This is a small, purely honesty-motivated
change, independent of extraction, and there is no reason to wait on it.

Separately, and worth keeping regardless of the rename: the *exception*
raised when a **plugin** (not the owner deliberately reaching in) hits an
unauthorized-access path should say, in its own message, what kind of limit
it is — "this is a policy refusal aimed at accidental plugin leakage, not a
security boundary against the process owner" — so a caller who only ever
reads exception text at a stack trace, never a docstring, still gets the
honest framing. That is about making *plugin* misuse loud, which is a
different goal from making *owner* access harder, and the two must not be
conflated the way the first draft's rejected option came close to doing.

### 3.5 The audit sentence itself — must be **structurally impossible to discard**

This is not one of the four README caveats, but it is the mechanism that
carries all of them, so it earns its own treatment. Today, nothing in
`cli.py`'s `run()` *requires* the caller to look at, log, or surface
`guard.audit.sentence()` — it happens to get embedded in every renderer's
output because corpuslens's own two renderers are written to do that, but
that is a discipline `render.py` chose to keep, not one `guard.py` enforces.
A second caller's renderer could simply not call `.sentence()` and nothing in
the Guard would notice or refuse.

**What would have to change:** the sentence needs to move from "a method you
can call" to "a thing you cannot get the result of a run without also
getting." Two candidate shapes:
- `Guard` exposes no bare `release()`/`admit()` results at all outside a
  context manager or a `finalize()` call that **returns
  `(results, sentence)` as a tuple the type system makes hard to destructure
  and discard** (Python can't truly prevent discarding a return value, but a
  dataclass wrapping both, with `sentence` as a non-optional field a
  static-typing-aware caller has to name, raises the bar).
- More forcefully: `scan_egress` (or its library equivalent) could **require
  the sentence as an argument** — `scan_egress(text, audit_sentence)` — and
  refuse to pass output through without it being present and non-empty. That
  turns "you forgot to attach the sentence" from a silent omission into the
  same fail-closed refusal every other wall violation gets.

### Summary table for §3

| README/guard.py caveat | Today's carrier | What a library needs instead |
|---|---|---|
| Default profile grants nothing | convention (empty dataclass defaults) | an exported, test-pinned "nothing granted" singleton as the only easy path |
| Weekly cadence not hidden | prose in three places | a named constant/property the type system exposes, and a mandatory clause in the generated sentence |
| Within-day bound is loose | plain `Optional[float]` | either a wrapper type carrying the caveat, or no raw per-event deltas in the public return type at all — only pre-aggregated stats |
| Not a sandbox against the owner | name-mangled attribute (looks stricter than it is) | rename to single-underscore (honest about reachability) — closing off the dot-path entirely was considered and rejected, since it moves the mechanism toward the sandbox posture the project explicitly refuses — and put the "not a sandbox" sentence in the plugin-facing exception text, not just the docstring |
| The sentence must accompany every result | one method call, easy to skip | make emitting output without the sentence a structural impossibility (required argument / bundled return type), not a rendering-layer courtesy |

---

## 4. The specific overclaim risks of publishing this

Mapping the README's own three "what it does NOT do" bullets onto what a
published library's *marketing surface* (README, docstring, PyPI page) would
be tempted to say, and how a library API would have to carry each one so the
temptation cannot be acted on silently:

1. **"Does not hide weekly cadence."** The overclaim risk: a library called
   something like "temporal-deidentification" or "privacy-preserving event
   timing" invites exactly the pitch this project's own README refuses —
   "de-identifies your timestamps." A user integrating it for, say, a
   support-ticket system would reasonably read a generic privacy library's
   marketing as "the output cannot be used to infer someone's schedule,"
   which is false for exactly the reason this project's founding observation
   states (a custody schedule was legible from timing shape alone). **Carry
   it:** the library's top-level docstring and README must lead with the
   same load-bearing sentence corpuslens's own README leads with — "relative
   time is process; the absolute anchor is person" — and the package name
   and pitch should avoid words like "anonymize" or "de-identify" that imply
   a stronger guarantee than "the absolute calendar anchor is quarantined."
   Concretely: ship the cadence caveat as an assertion in the library's own
   test suite that a downstream user's CI can adopt verbatim (mirroring
   `test_weekly_cadence_IS_reconstructable_documented_not_hidden`), so the
   caveat is something a user's own test suite can pin, not just prose they
   might not read.

2. **"Does not fully hide within-day time-of-day."** The overclaim risk is
   sharper for a library than for corpuslens itself, because corpuslens
   controls every analyzer that ever sees a `delta_prev_s` (there are six,
   all reviewed, and the README explicitly documents that `tempo` withholds
   cumulative span on purpose). A **library** hands raw deltas to arbitrary
   downstream code the maintainers will never review, and per §3.3, nothing
   stops that downstream code from doing the one aggregation (summing
   within-day deltas) that produces the local-clock bound. This is the
   single largest gap between "safe inside this repo" and "safe as a
   library" identified in this document. **Carry it:** per §3.3, seriously
   consider not shipping raw per-event deltas as a stable public return type
   at all — ship only pre-aggregated within-day statistics the library
   computes itself, the way corpuslens's own `tempo` analyzer already
   chooses to. If raw deltas are kept for legitimate use cases (a caller
   building their own tempo analyzer, which is a large part of why anyone
   would want this library instead of corpuslens itself), the wrapper type
   from §3.3 and a docstring on it that names the exact bound
   ("a 21-hour cumulative span puts the first event before ~03:00 local")
   are the minimum bar, not a nice-to-have.

3. **"Is not an adversarial sandbox against the owner."** The overclaim risk
   for a library is different in kind from the first two: it is not about
   what data reaches an analyst, but about what a library's *marketing*
   implies about its threat model. A generic "capability-gated data access"
   library invites being described (by someone other than its author — a
   blog post, a "cool library I found" tweet, an internal wiki page at some
   company that adopts it) as "enforces access control" or "prevents
   unauthorized access," full stop, dropping the "against a plugin, not the
   process owner" qualifier corpuslens's own docs carry today. That
   framing-drift is exactly the failure mode named in IDEAS.md's own words:
   "a library gets used by people who did not read `guard.py`" — and a
   security-adjacent library is unusually likely to be evaluated by someone
   skimming its README for whether it satisfies an actual security
   requirement, then deployed on that skim. **Carry it:** per §3.4, the
   exception raised on an internal-boundary violation should state the
   threat model in its own text (not just the docstring), and the library's
   name and top-line pitch should avoid "access control" / "security
   boundary" framing in favor of language that names the actual property:
   something closer to "accidental-leak guard" or "plugin containment,"
   words that do not invite the sandbox reading in the first place. A
   `SECURITY.md` for the library, mirroring this repo's own (which
   explicitly separates "wall breach" from "disclosed limit, by design" for
   exactly the owner-boundary case), is close to mandatory — and should ship
   from the library's first release, not be added after the first issue
   filed by someone who assumed otherwise.

A fourth risk, surfaced directly by §2c and not one of the README's three
either: **"there is no switch to grant a capability" is a claim about the
*host CLI*, and a library cannot make it survive contact with a host that
ships a subcommand whose whole job is granting one.** corpuslens's own
`fingerprint` design (§2c) already sits on this line — IDEAS.md itself flags,
unresolved, whether that subcommand is or is not "a CLI flag to grant
capabilities" in substance. A published library that lets *any* downstream
integrator build the equivalent of `fingerprint` — a command that constructs
a non-default `Profile` and hands it to the Guard with no further gate —
would let that integrator advertise "no CLI flag grants access" in their own
docs (copying the phrase from this library's own marketing) while shipping
exactly such a flag under a different name. **Carry it:** the library's docs
should state this limit explicitly and by name — "a host application can
always build a command whose purpose is to construct a granting `Profile`;
this library can make that act visible and audited, it cannot make it
impossible" — rather than let "no CLI flag" travel as an implied property of
the library itself when it is actually a discipline corpuslens's own `cli.py`
chose to hold in the one file that constructs `Profile` objects.

A fifth, meta-level risk worth naming even though it is not one of the
README's three: **the library's own version number would become a
compatibility promise about a safety property**, which is a new kind of
overclaim risk this project has not had to face yet (per the README's own
"0.1.0 is a spine... not a 1.x compatibility promise" and the
`BUGS.md`-documented incident where the release pipeline accidentally
published `1.0.0`). A capability-gating library reaching "1.0" implicitly
tells adopters "the set of capabilities, and what each one means, is now
stable" — which is a much heavier claim than "the CLI's interface is
stable," because a stable *capability name* is a stable *promise about what
that name does not leak*. That argues for the semantic-versioning discipline
IDEAS.md itself names as unsolved elsewhere ("Metrics that stay comparable
across tool versions," Further out and harder) to exist for the Guard's
capability set specifically, before a 1.0 of the extracted library, not
after.

---

## 5. Migration sketch

This is a sketch for *when* the trigger in §6 is met — not a plan to execute
now.

### What moves

- `guard.py`'s general mechanism (§1): `Profile`, `WallError`,
  capability-gating shape of `release()`, the egress-scan *algorithm*
  (re-scan rendered text for literal forbidden values, allow released
  classes), and the `AuditRecord`/sentence-building *pattern* — generalized
  to not know about `calendar_time`/`local_tz` by name, but instead operate
  over a caller-supplied mapping of `{capability_name: (quarantined_value,
  governing_capabilities)}`.
- The redesigned interfaces from §2: a content-reveal primitive alongside
  `resolve_ref` (for labelling mode), and — the larger one — capability
  gating decoupled from "the one `Quarantine` this Guard was built with," so
  a Guard can gate an arbitrary caller-named resource (for the leakage
  demonstration, per §2c's correction). Share mode turned out to need
  nothing new from `Guard` itself (§2a) — it is evidence the *renderer* layer
  needs a coarsening contract, not that `guard.py` does. All of this needs to
  exist and be exercised *before* extraction, per §6's trigger, so extraction
  records interfaces already proven rather than inventing them at split time.

### What stays in `corpuslens`

- `Quarantine`'s specific fields (`base_date_iso`, `local_tz`, `ref_map`) and
  the mapping from corpuslens's capabilities (`calendar_time`, `local_tz`,
  `person_inference`) to those fields.
- The claim-type allowlists (`PROCESS_CLAIM_TYPES`, `PERSON_CLAIM_TYPES`) —
  corpuslens's ontology, not the library's.
- `Guard.admit()`'s specific two-tier claim logic, rebuilt on top of the
  library's generic capability-gating primitive rather than duplicating it.
- All adapter code (`ingest/`), all analyzers (`analyze/`), `cli.py`,
  `render.py` — none of this is the Guard; it is the Guard's one caller.

### The shim

A thin `corpuslens.guard` module would become an adapter over the library:
construct the library's generic `Guard` with corpuslens's specific
capability→field mapping and claim allowlists supplied as data, and re-export
the same `Guard`, `Profile`, `WallError`, `DEFAULT_PROFILE`,
`KNOWN_CAPABILITIES` names corpuslens's own `cli.py` and `tests/test_wall.py`
already import, so nothing outside `guard.py` itself needs to change on day
one of the split. The shim's whole job is to make the split invisible to
`cli.py` — if `cli.py` needs to change at all to keep working, the split
was not designed correctly.

### How `tests/test_wall.py` would split

Looking at its five test classes against the general/specific line from §1:

- `ReleaseDoorTests`, most of `EgressScanTests`, and the "sentence" shape
  assertions in `AuditSentenceTests` test the **general mechanism** (fail
  closed on unknown/ungranted/missing-justification/no-token, egress scan
  allows released classes and refuses unreleased ones, error never echoes
  the leaked value) — these move to the library's test suite, parameterized
  over an abstract quarantined-field name instead of `calendar_time`
  specifically.
- `ClaimGateTests` and `HonestBoundaryTests` are **corpuslens-specific** —
  they assert things about `PERSON_CLAIM_TYPES`, `Event`'s actual fields,
  and the actual `claude-code` adapter's cross-midnight censoring. These stay
  in `corpuslens`'s test suite, now exercising the shim rather than the
  library's internals directly.
- The two most load-bearing tests —
  `test_weekly_cadence_IS_reconstructable_documented_not_hidden` and
  `test_supported_path_cannot_recover_absolute_anchor` — should exist **in
  both places**, not just one: the library needs its own generic version
  (asserting the *mechanism* can't be tricked into recovering a quarantined
  value through the supported door) and corpuslens needs to keep its own
  concrete version (asserting *this specific* `Quarantine`'s fields, with
  *this specific* adapter's data, produce the same guarantee end to end).
  Deleting the corpuslens-side version because "the library tests it now"
  would be exactly the kind of drift CONTRIBUTING.md warns against — a
  claim's test moving further from the code that has to keep it true.

---

## 6. Recommendation on timing

**Agreeing with IDEAS.md's "not first," and more strongly than before working
through §2.** The Sequencing paragraph's stated reason is that the Guard has
one caller and splitting now freezes an interface nothing has exercised.
Having now worked through the actual specification of the three named
callers, the reason is stronger than "no second caller yet," and the
strongest single piece of evidence is §2c: this document's own first draft,
written by a careful reader of `guard.py` and `model.py` with no other
information, **guessed the wrong shape** for the leakage demonstration —
"an analyzer that requests a capability from inside `run(events)`" — when
the actual spec is a command that gates an arbitrary external file with no
`Quarantine` behind it at all, and carries an open question (does invoking it
implicitly grant a capability?) that touches a load-bearing claim in `cli.py`
nobody had reason to revisit before this. If a careful reading of the
existing mechanism produces a plausible-but-wrong interface guess for even
one of the three named callers, extracting a library *before* that caller's
real shape is known would freeze exactly that kind of wrong guess as public
API — which is precisely the risk the Sequencing paragraph names, now with a
concrete instance of it happening to this document rather than a hypothetical.

**The trigger condition, more specific than "when a second caller exists":**
extraction is ready when **at least two** of the three near-term callers
(share mode, labelling mode, leakage demonstration) are built and merged
*inside* `corpuslens` — using whatever ad hoc, corpuslens-internal
extensions to `guard.py` each one needs (share mode may need none, per §2a;
labelling mode needs a content-reveal primitive, per §2b; the leakage
demonstration needs capability-gating decoupled from the one `Quarantine`
object, plus a resolved answer to the CLI-invocation-as-grant question, per
§2c) — and, critically, those extensions are compared against each other for
what they have in common. Two real, working extensions to the same file are
enough evidence to tell "general mechanism" from "one caller's convenient
hack" apart; one is not, and the Sequencing paragraph's own judgment about a
single caller stands. A third data point (all three built) would be
stronger still, but is not necessary — two independently-motivated
extensions that turn out to want the same underlying primitive is the actual
signal to watch for, not a headcount. Given how different the three callers'
needs turned out to be (§2's closing table), it is also plausible that even
two of them built will show *less* commonality than IDEAS.md's grouping
implies — share mode needing essentially nothing from `Guard` is itself a
data point that "the mechanism" may be smaller than `guard.py`'s 229 lines
suggest, and that too is worth learning before, not after, a split.

Until then, the highest-value guard-adjacent work is what §3 describes
directly: hardening the *existing* single-caller Guard's promises (the
name-mangling-vs-honesty mismatch in §3.4 is worth fixing regardless of
extraction, since it is a live gap between what `guard.py`'s own docstring
claims and what the code does), because every one of those fixes is strictly
useful to corpuslens today and makes the eventual extraction's §3 section
shorter, not because extraction is imminent.
