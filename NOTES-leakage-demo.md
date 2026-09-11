# NOTES — the leakage demonstration (IDEAS.md, "Further out, and harder")

Working notes for the branch `claude/expand-leakage-demo`. Not a doc a
reader needs; a record for whoever picks this up next, including a future
me. This file exists instead of edits to README.md/IDEAS.md because seven
agents are working on this repo in parallel this session — those two files
are theirs to reconcile; this is the diff they'd need to fold in.

## What this branch built, in one paragraph

`corpuslens/analyze/fingerprint.py::timing_fingerprint()` — a pure,
module-level function taking a sequence of absolute timestamps supplied
directly by the caller (never read out of the Guard, never derived from an
`Event`, which cannot carry one). It reports hour-of-week histogram
concentration (Shannon entropy in bits, and bits below uniform — "roughly
how many bits of schedule this file carries", IDEAS.md's own phrase) and
whether a ~7-day period is present and how strongly (a day-bucketed Pearson
autocorrelation at lag 7, stdlib-only, no FFT, with its rank among the
file's own other lags for context). It never returns a weekday label, a
clock hour, a date, or which hour-of-week bin is the peak, and it never
computes a safe/unsafe verdict. `tests/test_fingerprint.py` holds all of
that, including a property test that the output is provably invariant to
where on the real calendar the same relative pattern sits (shifting every
input timestamp by an arbitrary non-round offset changes nothing in the
output — the function cannot leak an absolute phase it never depends on).

It is **not** wired into the analyzer registry `corpuslens run` uses, and
there is **no** new CLI subcommand. Both omissions are deliberate; see below.

## What was deliberately NOT built, and why

### 1. No `corpuslens fingerprint <file>` CLI subcommand

This is IDEAS.md's own proposed shape for the feature, and its own entry
names the reason it's blocked: building that command means the CLI has to
construct *some* profile or capability for a Guard-free, owner-named-file
command — and `cli.py`'s docstring states there is deliberately no CLI flag
that grants a capability. Building the flag to make this one command work
resolves that tension by fiat, in the direction the sentence exists to
prevent. This task was explicit that I must not do that, and I agree with
the reasoning independent of being told: the sentence is a promise about
*every* subcommand, and carving out one exception because its purpose is
sympathetic is exactly how a wall gets a hole nobody voted on. See the
design note below for what would have to be decided before this can be
resolved either way.

### 2. Not registered via `@register(...)` into the default analyzer battery

This is a second, independent blocker from the CLI one above, and I want it
on record because IDEAS.md's entry doesn't call it out explicitly — I found
it by reading `guard.py` and `model.py` together:

`leakage_demonstration` sits on **`PROCESS_CLAIM_TYPES`** in `model.py`, not
`PERSON_CLAIM_TYPES`. `Guard.admit()` only gates `PERSON_CLAIM_TYPES` behind
`person_inference` + an owner token — every process claim, `leakage_demonstration`
included, is admitted under the **default** profile with no gate at all
(`guard.py`, `admit()`, the `continue` on the first branch). If this function
were wired in as a normal analyzer, it would run on every `corpuslens run`
against every ordinary corpus — the exact outcome this task said to avoid,
and I read that as consistent with the project's own claim allowlist design,
not in tension with it: the claim type was named for a "quarantined class",
but nothing in `guard.py` actually quarantines it, because it isn't shaped
like a person claim.

It's also structurally unfit for that registry independent of the gating
question: analyzers receive `events: list[Event]`, and an `Event`'s `time`
is a `CoarseTime` — day offset + a within-thread, cross-midnight-censored
delta. There is no absolute timestamp anywhere on an `Event` to compute
this over; that absence is the wall working as designed (see `model.py`'s
`CoarseTime` docstring). So even ignoring the gating gap, there is nothing
for a `leakage_demonstration` analyzer to legitimately receive through the
normal `events` argument.

**Options for closing the gating gap, for whoever picks this up**, not
chosen here:
  a. Move `leakage_demonstration` to a claim class of its own that *is*
     gated like `PERSON_CLAIM_TYPES` (a capability, or a new "quarantined
     but process-shaped" tier) — the more honest fix, but it's a change to
     `model.py`'s ontology and `guard.py`'s `admit()`, both load-bearing
     files this task was told not to resolve by accident, and I did not
     want to make that call inside a task whose brief was "build the
     computation, not the command."
  b. Leave the claim type as process-shaped (correct: the claim really is
     about the file, not the person) and rely entirely on never registering
     an analyzer that declares it against `events` — which is what this
     branch does. The claim type existing on the allowlist with nothing
     implementing it is itself a documented, deliberate gap (see IDEAS.md's
     own line: "nothing implements either").

I lean toward (b) is the more honest state for *this* function specifically,
because its real input (a file the owner names) was never going to travel
through `events` anyway — but I'm flagging (a) because the allowlist's
comment ("quarantined class") reads as a claim the registry doesn't
currently back up, and that gap could bite a *future* analyzer that tries to
declare `leakage_demonstration` against real `Event` data believing the
claim type alone protects it.

## Design note: how could a non-default profile ever get built for a user-facing command?

This is the question IDEAS.md's entry raises and does not answer, and this
task told me explicitly not to answer it either. Options, with tradeoffs,
picking none:

**A. A new subcommand that is architecturally exempt from "capability", not
granted one.** `corpuslens fingerprint <file>` never touches the corpus, the
adapters, the `Quarantine`, or a `Guard` at all — it reads a file the owner
named directly and calls `timing_fingerprint()` on timestamps it parses out
of that file. No `Profile` is constructed because none of the wall's
machinery is in the path; `cli.py`'s sentence ("no CLI flag to grant
capabilities") stays literally true because nothing is being granted — there
is no Guard in this command to grant anything to.
  - *For:* the sentence survives unchanged; the command is simple; it matches
    IDEAS.md's own description ("takes any timestamped export the owner
    holds... this tool's own quarantine if the owner grants it").
  - *Against:* it's a distinction a skeptical reader could call cosmetic —
    "the tool has a command that computes a leakage report over absolute
    time" is true either way, and whether a `Guard` object sits in the call
    stack doesn't change what left the wall if the *input* to this command
    could be this tool's own quarantine. It also means this command has none
    of the wall's protections (no audit sentence, no egress scan) over
    *its own* output, which is arguably the one place in the tool where a
    timing-shaped report is being emitted on purpose — the audit machinery
    might be worth having even though nothing is technically "granted".

**B. A profile-constructing entry point that is a library function, not a
CLI flag.** Keep `cli.py` exactly as it is (still no flag), and instead
document a supported pattern in `guard.py` or a new small module: "owners
who want to run `fingerprint` over their own quarantine write a five-line
script that constructs `Guard(quarantine, Profile(capabilities={"calendar_time",...}, owner_token=...))`
themselves." This is *already* how every other capability grant in this
project works (`cli.py`'s docstring says so explicitly), so it needs no new
mechanism — it needs someone to decide that `fingerprint`-over-quarantine
is docs, not a subcommand, the same way calendar/timezone release already is.
  - *For:* zero new code, zero new surface, perfectly consistent with the
    existing "a grant is an owner-side code change" claim — this option
    doesn't just avoid contradicting that sentence, it's the sentence's
    intended shape.
  - *Against:* it means `corpuslens fingerprint` never exists as a command a
    stranger can run without writing Python, which is most of the product
    value IDEAS.md describes ("makes that test runnable"). A tool that only
    the already-technical can use to check *their own* export is a smaller
    win than the entry envisions.

**C. A capability that is scoped to "files the owner names on this
invocation", separate from the corpus's own quarantine.** Add a new
`KNOWN_CAPABILITIES` entry, something like `external_timing_file`, that
`Guard` grants automatically and only for a command whose sole input is a
path argument the user typed on this invocation, never for anything that
touches the ingested corpus or its `Quarantine`. The reasoning: the wall
exists to keep the corpus's absolute anchor from leaking into an
analyzer's output *by default*; a file the owner explicitly named on the
command line was never inside that boundary to begin with, so "granting"
access to it isn't the same act as granting access to the corpus's own
quarantined calendar anchor.
  - *For:* keeps the "no flag grants a capability *over the corpus*" claim
    intact in spirit, while giving `fingerprint` a real CLI command.
  - *Against:* this is the option most likely to be read as motivated
    reasoning — defining a new capability whose only property is "the one
    kind of capability the CLI is allowed to grant" is uncomfortably close
    to adding the flag and renaming it. It also sets a precedent: the next
    feature that wants a CLI-grantable capability can point at this one as
    the reason its own carve-out is fine too. `cli.py`'s sentence is a
    single, simple, auditable claim today; this option is the one most
    likely to erode it over successive "just this one" exceptions.

**D. Don't build the subcommand at all; document the refusal.** Ship
`timing_fingerprint()` as a library function only (this branch's actual
deliverable) and record, in IDEAS.md's own voice, that the CLI shape of this
feature is refused until the collision above is resolved on purpose rather
than by a convenient commit. This is the "safe" default in the sense the
project already applies elsewhere (see IDEAS.md's "Population reference
points" and "A lens that stays a lens" entries, both of which land on
documented refusals) — but it's also the option that makes the least of
GRADING.md question 9 actually runnable by a non-technical reader, which is
the entry's whole stated motivation.

I'm not picking one. (A) is closest to "ship something now"; (B) is closest
to "change nothing, document a pattern"; (C) is the one I'd push back on
hardest if someone proposed it; (D) is where this branch actually leaves
things.

## Doc changes this would need once someone decides

Not made here (README.md/IDEAS.md are off-limits this session):

- **README.md**, "The wall" section: a one-line pointer that
  `corpuslens.analyze.fingerprint.timing_fingerprint()` exists as a library
  function for exactly the GRADING.md Q9 self-test, with the same "owner can
  always read their own quarantined data" framing already used for the
  wall's other owner-side escape hatches — and an explicit note that it is
  *not* a CLI command yet, and why (link to the IDEAS.md entry).
- **IDEAS.md**, "The leakage demonstration" entry: append a short status
  update — the computation is built and tested (`corpuslens/analyze/fingerprint.py`,
  `tests/test_fingerprint.py`); the CLI subcommand and the capability-gating
  question for the claim type are both still open, with a pointer to this
  file's design-note options A–D so the next person doesn't re-derive them.
  Do **not** resolve the entry's own open question in that edit — append,
  don't rewrite the "why it is Further out" paragraph.
- **GRADING.md**, question 9: could gain a one-line "a runnable version of
  this test now exists: `timing_fingerprint()`, no CLI yet" — optional, and
  only if whoever merges this thinks a rubric question should point at
  library code that isn't yet a command.
- **model.py**: if design option (a) under "not registered" above is ever
  chosen (moving `leakage_demonstration` to a gated tier), that comment on
  `PROCESS_CLAIM_TYPES` ("quarantined class: proves a leak, never ships
  data") needs to either become true (move the claim type and gate it) or
  be corrected to say it isn't currently gated — right now the comment
  reads as a stronger claim than `guard.py`'s `admit()` actually enforces
  for this specific claim type, and CONTRIBUTING.md's one rule is that
  claims must match code.
