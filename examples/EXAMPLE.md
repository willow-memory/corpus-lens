# Example run

A complete corpuslens run on the small synthetic corpus in
[`sample-corpus/`](sample-corpus/) (three Claude Code sessions, 21 lines). It is
**fully reproducible** — run the command below and you get this output
byte-for-byte, which is corpuslens's reproducibility guarantee (relative time
only; no host-timezone drift) working in the open. The corpus is synthetic, so
nothing here is anyone's real data.

```bash
corpuslens run examples/sample-corpus --adapter claude-code
```

## The whole report

```
# corpuslens report

> This run read 21 events (dropped 0, counted not hidden), ran 6 process
> analyzers under profile 'default', and was granted nothing beyond process
> analysis. No absolute calendar date, timezone, or filename left the wall;
> relative day and within-day tempo did — these preserve weekly cadence, and on
> a day a single thread spans for many hours they loosely bound the local
> time-of-day (never the timezone or the date).

> This report's battery answers GRADING.md's first four questions — where your
> intent arrives, who writes the code, whether you deliberate on purpose, and
> your threads' shape — each section below says which one it answers and how
> fully. Questions 5-8 (can a stored claim be demoted; when a negative result
> was last recorded; whether an agent can grant itself anything; whether checks
> fail closed) and questions 9-10 (whether your timestamps are a fingerprint;
> who carries the continuity across a session gap) are not corpus-measurable
> from session logs at all — GRADING.md gives each of those its own manual
> test, not a number this tool computes.
```

Then the findings, which is what the report leads with:

```
## What this run found

- **steering_density** — 70.0% of your prompt turns arrive mid-task rather than in a session's opening prompt.
- **thread_shape** — 3 thread(s), picked back up 1 time(s) after a gap of 2 days or more; at the busiest, 2 ran on the same day.
- **composition_mix** — You authored code in 0.0% of your prompts and referred to existing code in 0.0%; 10.0% deliberate before building.
- **clarification_pull** — The machine asked a clarifying question you then answered in 10.0% of its turns.
- **tempo** — Your prompts arrive a median 750.0s apart within a thread (measurable on 60.0% of eligible turns; the rest have no gap to measure).
- **thread_span** — Half your threads span 1 day(s) or less; the longest stays open across 4.
```

A reader who stops here has the run. Each section below then repeats its
sentence, names the denominator it is out of, gives the direction guidance, and
prints the full numbers — nothing is summarized away, and the prose and the JSON
come from the same result. Every section of this run also carries
`*Small sample (n = 10): read the direction, not the decimal.*`, because this
synthetic corpus is 21 lines: at that size a percentage is a story about three
turns, and the report says so rather than letting the decimal imply precision it
does not have.

**Read the audit line first.** It is the wall reporting on itself: how many input
lines became events, how many were dropped (and that the count is not hidden),
what capability was granted (none), and — precisely — what left the wall and what
did not. Notice what is *absent* from everything below: no message text, no
calendar date, no filename. That is why this report is safe to paste into a
public README. The tool is built so its output is shareable; this is that
property, demonstrated.

### steering_density — where does your intent arrive?

*GRADING.md: question 1 — this is the analyzer's own declared mapping,
rendered in the report right under the headline.*

```json
{
  "sessions": 3,
  "mid_task_share_pct": 70.0,
  "work_session_median_turns": 4,
  "opener_median_words": 17,
  "reference": { "measured_director": "96.8% mid-task, 26-turn work sessions",
                 "swe_bench_tau_bench": "0% mid-task by construction" }
}
```

70% of the operator's turns arrive **during** a session, not in the opening
prompt — this is a directing pattern, not a one-shot-spec pattern. The reference
poles: a measured power-user director sits at 96.8% mid-task; SWE-bench / τ-bench
permit 0% by construction (one upfront spec, no mid-task turns). A higher number
means more of your intent lands while the machine is already working.
`measured_director` is **one person's own corpus (N=1)**, not a population — the
report says so beside that row, and adds that until `corpuslens label` +
`corpuslens score` measure the classifiers' own error on this corpus, nobody
knows how much of a gap from it is you and how much is the regex.

### thread_shape — how do you drop and resume work?

*GRADING.md: part of question 4 — this analyzer counts resumption gaps and
same-day concurrency, but question 4 also asks for a >=30-day bucket, monthly
counts, and whether a return was productive; none of those are computed, so
the declaration says "part of", not "question 4".*

```json
{ "threads": 3, "resumptions_2to6d": 1, "concurrency_peak": 2 }
```

One thread (the dashboard project) went quiet and was **resumed after a 3-day
gap** — that is the single `resumptions_2to6d`. Buckets are disjoint day-gap
ranges (2–6d, 7–13d, ≥14d); sum them for total resumptions ≥2d. All of it is
derived from **log-field timestamps only** — never date-strings grepped from
content, which once inflated a count 10×. The dates are relative offsets, so the
weekly rhythm survives but the calendar does not.

### composition_mix — who writes the code, and do you deliberate?

*GRADING.md: question 2 for authored/code-ref (this is exactly GRADING.md's
stated method — a domain-population comparison); part of question 3 for
`delib_pct`, which reports the discussion-channel share but not whether those
prompts pull longer responses, the other half of what question 3 asks.*

```
Against the reference: authored 0.0% vs 14.5% (below), code-ref 0.0% vs 36.0%
(below), deliberation 10.0% vs 3.2% (above) — WildChat coding population.
```

```json
{
  "authored_code_pct": 0.0,
  "code_ref_pct": 0.0,
  "delib_pct": 10.0,
  "reference": {
    "wildchat_coding_population": { "authored_pct": 14.5, "read_ref_pct": 36.0, "delib_pct": 3.2 },
    "measured_director_n1":       { "authored_pct": 6.3,  "read_ref_pct": 18.3, "delib_pct": 5.2 }
  }
}
```

The report states that comparison itself, in the line above: the operator
authored no code and referenced none — **well below** the coding-domain
population (14.5% / 36%). (`near` is a real verdict there too: a gap under 3
points is inside the classifiers' own error, and a regex heuristic does not get
to call it.) Per the analyzer's own `reading` guidance,
below the population means *the machine holds the code and you direct it*; above
it would mean *you bring the code to the machine*. Deliberation runs 10% here —
above the coding population's 3.2% — because one session opened with "lets talk
about options … the tradeoffs" before any building. That is the teaching channel,
summoned on purpose. (These are regex heuristics — grade the direction against
the reference, spot-check before you cite a number.)
`wildchat_coding_population` (and `wildchat_all`, `oasst_general_chat`) are
named population aggregates and stay that way in the report; only
`measured_director_n1` gets the "author's own corpus (N=1)" label and the
one-person-gap sentence — the two kinds of reference point are never merged.

### clarification_pull — does the machine ask, and do you answer?

*GRADING.md: none of the numbered questions directly. Question 3 is the
closest in theme, but it asks about YOUR prompts opening a discussion channel
— this measures the machine asking and you answering, the reverse direction,
which GRADING.md does not pose as a question. Naming that plainly, rather than
filing this under "question 3" because the module is about deliberation, is
the check IDEAS.md asks for.*

```json
{ "assistant_turns": 10, "clarification_forks_pct": 10.0,
  "reference": { "measured_cli": 3.4 } }
```

One assistant turn asked a real question ("fail hard on an unknown key, or ignore
it?") and the operator answered it — that is the one clarification fork. On a
CLI corpus this is the steering seam; on a Cursor corpus it is near-absent (and
the analyzer can't compute it there — Cursor logs carry no assistant turns, which
the reference note says plainly rather than printing a number it didn't measure).
Both `measured_cli` and `measured_cursor_note` are the same one person's data,
split by tool — the report labels both rows N=1, not a population.

### tempo — how fast do your turns arrive?

*GRADING.md: none of the numbered questions directly — thematically closest
to question 1 (arrival) and question 4 (thread rhythm), but neither asks for
second/minute-level inter-turn gaps. A supporting signal, not one of the ten
measurements, and the report says so rather than borrowing a question number
for it.*

```json
{ "n_deltas": 6, "eligible_turns": 10, "delta_coverage_pct": 60.0,
  "median_gap_s": 750.0, "p25_gap_s": 510.0, "p75_gap_s": 1005.0,
  "burst_pct": 0.0, "resumed_pct": 0.0 }
```

Half the operator's gaps sit around **12–13 minutes**: this synthetic operator
neither fires volleys (`burst_pct` 0 — nothing inside a minute) nor walks away
mid-thread (`resumed_pct` 0 — nothing past half an hour). Note the
**60% coverage**: four of the ten eligible turns have no gap at all, because
they open a thread or follow a censored midnight crossing. Those turns are
counted as uncovered and left that way — an interpolated gap would be
indistinguishable from a measured one downstream, which is exactly the
fabrication the wall exists to prevent. A `cursor-store` corpus reports **no
tempo at all** for the same reason: that store clocks the machine's tool steps,
never your prompts.

No *cumulative* within-day span is published here, deliberately. The README
discloses that a long span loosely bounds the local clock hour; percentiles over
individual gaps do not sharpen that bound, and no analyzer may.

### thread_span — how long does a thread stay open?

*GRADING.md: part of question 4 — span and density are the complement to
thread_shape's resumption gaps, but question 4 also asks for per-day/month
activity counts and whether a return was productive; neither is reported
here either.*

```json
{ "threads": 3, "single_day_threads_pct": 66.7, "median_span_days": 1,
  "max_span_days": 4, "median_active_days": 1, "median_density": 1.0 }
```

Where `thread_shape` counts resumption *gaps*, this counts the **span they sit
in** — different facts about the same thread. Two of the three threads open and
close inside one day; the dashboard thread stretches across a 4-day span it is
only active on 2 of. A median density of 1.0 says the typical thread here is
worked and closed; a low density beside a long span would say you keep threads
open for weeks and return to them. Spans are differences between relative day
offsets, so they carry weekly cadence and no calendar date.

## What this example demonstrates

- **The wall works and is legible.** Every number above is process; no content,
  date, or filename appears. The audit line states that, and you can verify it by
  reading the output.
- **A finding, not a dump.** Each analyzer writes its own sentence, beside the
  computation that knows what its denominator means — so the prose can never
  drift from the number under it, and an analyzer that *cannot* compute says so
  in words instead of rendering an empty section that would read as a zero.
- **Reproducibility.** Re-run the command on any machine, in any timezone — the
  numbers are identical, because the analysis is relative-time-only.
- **Honest denominators and drops.** Every rate names what it is out of; the
  audit line counts every dropped input line.
- **Reference, not verdict.** The tool sits your numbers beside a measured N=1
  and public population aggregates. It does not grade you; it gives you something
  to grade *against*.
- **Whose corpus, and which question.** `measured_director`/`measured_director_n1`/
  `measured_cli` are one person's own corpus, labelled N=1 beside every row so a
  gap from them never reads as a gap from a population — the named WildChat/OASST
  rows stay visibly distinct. And each section names which of GRADING.md's ten
  questions it answers, in full or "part of"; the report also says once, up
  front, that questions 5-8 and 9-10 are not corpus-measurable at all.
