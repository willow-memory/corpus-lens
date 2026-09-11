"""Where does your intent arrive? (GRADING.md question 1 + 4's relative half)

All computations use relative time only (day offsets, per-thread ordering).
No calendar is reachable from here — that is the wall doing its job.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from ..model import AuthorClass, DataType
from . import register, semantic_hash

# What `steering_density`'s number MEANS: an operator prompt turn is "mid-task"
# iff it is not the first prompt in its thread, filtered to prompts with
# `char_count >= 12` (de-injected). The only semantic knob is that threshold —
# change it and a 62%->81% move in the headline could be the filter, not you.
_MIN_CHARS = "12"
_STEERING_DENSITY_INPUTS = (_MIN_CHARS,)
_STEERING_DENSITY_HASH = "b5c69e2b7a6f9c31"


@register("steering_density", claims=("steering_density",),
          denominator="operator prompt turns with >=12 characters (de-injected)",
          version=1, semantic_hash=_STEERING_DENSITY_HASH,
          semantic_inputs=_STEERING_DENSITY_INPUTS)
def steering_density(events):
    sess = defaultdict(list)
    for e in events:
        if e.author_class is AuthorClass.OPERATOR and e.data_type is DataType.PROMPT \
                and e.features.get("char_count", 0) >= 12:
            sess[e.thread_id].append(e)
    if not sess:
        return {"error": "no operator prompts found"}
    turns_per = [len(v) for v in sess.values()]
    total = sum(turns_per)
    mid = total - len(sess)
    multi = [t for t in turns_per if t >= 2]
    openers = [v[0].features["word_count"] for v in sess.values()]
    followups = [e.features["word_count"] for v in sess.values() for e in v[1:]]
    mid_pct = round(100 * mid / total, 1)
    return {
        "headline": (f"{mid_pct}% of your prompt turns arrive mid-task rather than in a "
                     f"session's opening prompt."),
        "n": total,
        "sessions": len(sess),
        "total_turns": total,
        "mid_task_share_pct": mid_pct,
        "single_turn_sessions_pct": round(100 * (len(sess) - len(multi)) / len(sess), 1),
        "single_turn_sessions_pct_denominator": "sessions (not turns) — this rate is per-session",
        "work_session_median_turns": statistics.median(multi) if multi else 0,
        "opener_median_words": statistics.median(openers),
        "followup_median_words": statistics.median(followups) if followups else 0,
        "reference": {"measured_director": "96.8% mid-task, 26-turn work sessions",
                      "swe_bench_tau_bench": "0% mid-task by construction"},
    }


@register("thread_shape", claims=("thread_shape",),
          denominator="threads with >=1 active day (relative days only)")
def thread_shape(events):
    days = defaultdict(set)
    for e in events:
        days[e.thread_id].add(e.time.day_offset)
    def resum(ds, lo, hi=None):
        """Count gaps between consecutive active days in [lo, hi). Buckets are
        DISJOINT so they never double-count a single long gap."""
        s = sorted(ds)
        return sum(1 for a, b in zip(s, s[1:]) if lo <= (b - a) < (hi or 10 ** 9))
    day_threads = defaultdict(set)
    for t, ds in days.items():
        for d in ds:
            day_threads[d].add(t)
    conc = [len(v) for v in day_threads.values()]
    resumptions = (sum(resum(d, 2, 7) for d in days.values())
                   + sum(resum(d, 7, 14) for d in days.values())
                   + sum(resum(d, 14) for d in days.values()))
    peak = max(conc) if conc else 0
    return {
        "headline": (f"{len(days)} thread(s), picked back up {resumptions} time(s) after a gap of "
                     f"2 days or more; at the busiest, {peak} ran on the same day."),
        "n": len(days),
        "threads": len(days),
        "resumptions_2to6d": sum(resum(d, 2, 7) for d in days.values()),
        "resumptions_7to13d": sum(resum(d, 7, 14) for d in days.values()),
        "resumptions_ge14d": sum(resum(d, 14) for d in days.values()),
        "buckets": "disjoint day-gap ranges — sum them for total resumptions >=2d",
        "concurrency_median": statistics.median(conc) if conc else 0,
        "concurrency_peak": max(conc) if conc else 0,
        "note": ("derived from log-field dates only; content dates once inflated this 10x. "
                 "Day gaps are relative — they preserve weekly cadence but not calendar dates."),
    }
