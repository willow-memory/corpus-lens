"""Rhythm: how fast do your turns arrive, and how are threads shaped in time?

Both analyzers here read RELATIVE time only — `delta_prev_s` (seconds since the
previous turn in the same thread, censored across midnight at ingest) and
`day_offset`. No calendar is reachable from here; that is the wall doing its
job.

ONE DELIBERATE OMISSION. Neither analyzer emits a per-day *cumulative* span
(first-to-last within one day). The README discloses that a long within-day
span loosely bounds the local clock hour — a 21-hour span puts the first event
before ~03:00 local. Percentiles over individual gaps do not sharpen that
bound; a published per-day span would. So the bound stays where it is
disclosed, and no analyzer here tightens it.
"""
from __future__ import annotations

import statistics

from ..model import AuthorClass, DataType
from . import register, semantic_hash

BURST_S = 60.0        # a follow-up inside a minute: still mid-thought
RESUMED_S = 1800.0    # half an hour later: you went away and came back

# `tempo`'s number MEANS: gaps bucketed at BURST_S/RESUMED_S, over prompts
# with >=12 chars. Move either threshold and "burst share" counts a different
# set of gaps under the same name.
_MIN_CHARS = "12"
_TEMPO_INPUTS = (str(BURST_S), str(RESUMED_S), _MIN_CHARS)
_TEMPO_HASH = "0195c217fe437f3c"

# `thread_span`'s number carries no classifier/threshold dependency — it is
# pure day-offset arithmetic (span, active-day density). Nothing to pin beyond
# saying so; a future change here (e.g. a minimum-span floor) should add real
# inputs and a version bump like its siblings.
_THREAD_SPAN_INPUTS = ()
_THREAD_SPAN_HASH = semantic_hash(*_THREAD_SPAN_INPUTS)


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


@register("tempo", claims=("tempo",),
          denominator="operator prompt turns (>=12 chars) carrying a within-day tempo delta",
          version=1,
          grading_question=("none of GRADING.md's numbered questions directly — thematically "
                             "closest to question 1 (arrival) and question 4 (thread rhythm), but "
                             "neither asks for second/minute-level inter-turn gaps; this is a "
                             "supporting signal, not one of the ten measurements"),
          semantic_hash=_TEMPO_HASH, semantic_inputs=_TEMPO_INPUTS)
def tempo(events):
    """Inter-turn gaps between your own prompts, within a thread and within a day.

    A turn has no delta when it opens a thread, when the previous turn was on
    another day (censored at ingest so the clock cannot be pinned at a
    midnight), or when the corpus never recorded a clock for prompts at all
    (`cursor-store`). Those turns are counted as uncovered, never imputed — an
    interpolated gap is indistinguishable from a measured one downstream.
    """
    turns = [e for e in events
             if e.author_class is AuthorClass.OPERATOR and e.data_type is DataType.PROMPT
             and e.features.get("char_count", 0) >= 12]
    eligible = len(turns)
    if not eligible:
        return {"error": "no operator prompts found"}
    deltas = [e.time.delta_prev_s for e in turns if e.time.delta_prev_s is not None]
    n = len(deltas)
    if not n:
        return {"error": ("no within-day tempo deltas in this corpus — every operator turn "
                          "opens a thread, follows a censored midnight crossing, or comes from "
                          "a store that does not clock prompts (cursor-store). Tempo is not "
                          "computable here, and is not guessed at."),
                "eligible_turns": eligible, "delta_coverage_pct": 0.0}
    q = statistics.quantiles(deltas, n=4) if n >= 4 else None
    median = round(statistics.median(deltas), 1)
    cov = _pct(n, eligible)
    return {
        "headline": (f"Your prompts arrive a median {median}s apart within a thread "
                     f"(measurable on {cov}% of eligible turns; the rest have no gap to measure)."),
        "n": n,
        "n_deltas": n,
        "eligible_turns": eligible,
        "delta_coverage_pct": cov,
        "coverage_note": ("uncovered turns open a thread, sit after a censored midnight "
                          "crossing, or come from a corpus with no prompt clock — never imputed"),
        "median_gap_s": median,
        "p25_gap_s": round(q[0], 1) if q else None,
        "p75_gap_s": round(q[2], 1) if q else None,
        "burst_pct": _pct(sum(1 for d in deltas if d < BURST_S), n),
        "burst_threshold_s": BURST_S,
        "resumed_pct": _pct(sum(1 for d in deltas if d >= RESUMED_S), n),
        "resumed_threshold_s": RESUMED_S,
        "reading": ("high burst share = you steer in volleys, several corrections per thought; "
                    "high resumed share = you leave the machine running and return. This is the "
                    "rate at which YOUR turns arrive — on a cursor-store corpus it would be the "
                    "machine's step rate, which is why that corpus reports no tempo at all."),
    }


@register("thread_span", claims=("thread_shape",),
          denominator="threads with >=1 event (relative days only)",
          version=1,
          grading_question=("part of question 4 — span and density are the complement to "
                             "thread_shape's resumption gaps, but GRADING.md's question 4 also "
                             "asks for per-day/month activity counts and whether a return was "
                             "productive, neither of which this reports"),
          semantic_hash=_THREAD_SPAN_HASH, semantic_inputs=_THREAD_SPAN_INPUTS)
def thread_span(events):
    """How long a thread stays open, and how densely it is worked.

    `thread_shape` counts resumption GAPS; this counts the SPAN they sit in —
    a thread touched on days 0 and 30 has one resumption and a 31-day span, and
    those are different facts about your process. Span is a difference between
    relative day offsets, so it carries no calendar.
    """
    days: dict = {}
    for e in events:
        days.setdefault(e.thread_id, set()).add(e.time.day_offset)
    if not days:
        return {"error": "no events"}
    spans: list = []
    densities: list = []
    for ds in days.values():
        span = max(ds) - min(ds) + 1          # inclusive: a one-day thread spans 1 day
        spans.append(span)
        densities.append(len(ds) / span)
    med_span = statistics.median(spans)
    return {
        "headline": (f"Half your threads span {med_span} day(s) or less; the longest stays open "
                     f"across {max(spans)}."),
        "n": len(days),
        "threads": len(days),
        "single_day_threads_pct": _pct(sum(1 for s in spans if s == 1), len(spans)),
        "median_span_days": med_span,
        "max_span_days": max(spans),
        "median_active_days": statistics.median(len(ds) for ds in days.values()),
        "median_density": round(statistics.median(densities), 3),
        "density_definition": "active days / (last day - first day + 1), per thread, median of that",
        "reading": ("density near 1.0 = threads are worked and closed; a low median density with "
                    "a long median span = you keep many threads open across weeks and return to "
                    "them. Spans are relative-day differences: they preserve weekly cadence and "
                    "carry no calendar date."),
    }
