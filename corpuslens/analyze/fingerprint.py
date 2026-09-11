"""corpuslens.analyze.fingerprint — the leakage-demonstration computation.

Spec: IDEAS.md, "Further out, and harder" -> "The leakage demonstration — the
one analyzer for the quarantined class". GRADING.md question 9 ("Are your
timestamps a fingerprint?") tells the reader to take a week of their own
exported metadata and try to reconstruct their schedule from timestamps
alone. This module is what makes that test runnable as a computation, without
attempting the part of the idea that is still unresolved.

WHAT THIS IS. `timing_fingerprint()` is a pure, module-level function. It
takes a sequence of ABSOLUTE timestamps supplied directly by the caller — not
read out of a corpus, not read out of the Guard, not derived from an `Event`
(an `Event.time` is a `CoarseTime`: relative day offset + a censored
within-thread delta, and it structurally cannot be turned back into an
absolute timestamp — see model.py and guard.py). The caller is the owner,
pointing this at a file they already hold in the clear: another tool's export,
a calendar dump, a sync log, or their own corpus's quarantine if they chose to
grant themselves that (see guard.py — the wall does not claim to stop its own
owner). That is what keeps this function's claim process-shaped even though
the computation touches absolute time: the claim is "this FILE leaks its
timing shape", not "this PERSON has this schedule".

WHAT IT REPORTS, AND WHY THAT LIST AND NO MORE:
  * `n` — how many timestamps were usable.
  * `hour_of_week_entropy_bits` / `hour_of_week_bits_below_uniform` — the
    concentration of the 168-bin (24h x 7d) hour-of-week histogram, in bits.
    A uniform week carries `log2(168)` ~= 7.39 bits of entropy and zero bits
    "below uniform"; a schedule concentrated into a few hour-of-week slots
    carries entropy near zero and most of those ~7.39 bits "below uniform".
    Reading `bits_below_uniform` as "roughly how many bits of schedule this
    file carries" is exactly the phrase IDEAS.md uses for this number.
  * `weekly_autocorr_lag7` / `weekly_autocorr_rank_pct` — whether a ~7-day
    period is present, and how strongly, as a continuous autocorrelation
    coefficient (see METHOD below) plus its rank among the other lags this
    same corpus could support. This is deliberately NOT collapsed into a
    present/absent boolean: a boolean needs a cutoff, and this project's rule
    is that a threshold is only added once it is defensible (see NO VERDICT).
  * `n_days_spanned` — context for how noisy the autocorrelation estimate is
    (a 10-day corpus cannot support a confident lag-7 read).

WHAT IT NEVER RETURNS, AND A TEST HOLDS THIS: no weekday label, no clock hour,
no calendar date, no identification of which hour-of-week bin is the peak.
The output is a verdict about the FILE's timing shape, never a description of
the person who produced it — printing "your peak hour-of-week bin is
Tuesday-2pm-equivalent" would be exactly the leak this function exists to
demonstrate the RISK of, not to commit itself.

METHOD, AND ITS LIMITS (stdlib only — no FFT is available or used). Weekly
periodicity is measured by bucketing events into whole-day counts relative to
the FIRST timestamp seen (day 0, day 1, ... — the same relative-offset framing
the rest of this project uses for calendar days, applied here to a file the
caller already holds in the clear), then taking the Pearson autocorrelation
of that per-day count series against itself shifted by 7 days
(`statistics.correlation`, stdlib, 3.10+). This is a simple, honest, and
crude instrument:
  * It only tests exact 7-day periodicity (and, for context, other integer-day
    lags up to `MAX_LAG_DAYS`). A schedule on a 5-day work-week, a rotating
    shift, or a period that drifts will not show up cleanly at lag 7, and this
    function will not find it — it is not a general spectral method.
  * Day buckets are relative to the first timestamp, not calendar-day
    boundaries in any timezone, and this function does not know or ask about a
    timezone. A rhythm that is real in local time can smear across two day
    buckets here.
  * Short spans give a noisy estimate: `n_days_spanned` is reported precisely
    so a reader does not trust an autocorrelation computed over three weeks
    the way they would trust one computed over three years.
  * Autocorrelation on count series responds to ANY 7-day-periodic amplitude
    change (more events on the same day-of-week each week), not specifically
    to "hours are similar to seven days ago" — a related but not identical
    question to the hour-of-week histogram above. The two numbers are
    deliberately reported side by side rather than merged into one score,
    because they measure different things and a merged score would hide that.

NO VERDICT — READ THIS BEFORE ADDING ONE. This function does not, and must
not, return "safe" or "unsafe", "identifiable" or "not identifiable". IDEAS.md
says why: a safe/unsafe verdict is a claim about how identifying a weekly
pattern is IN GENERAL, and the closest prior art (de Montjoye et al., *Unique
in the Crowd*, *Unique in the shopping mall*; Mayer, Mutchler & Mitchell on
telephone metadata) measured different data under different conditions. Until
that number can be defended for THIS kind of file, the honest output is the
measured concentration and the measured period strength, for the owner to
read — not a threshold applied on their behalf. A function that collapses
these numbers into "safe" is the overclaim this whole project exists to
forbid (CONTRIBUTING.md's one rule). Do not add one here without a defensible,
cited number to back it, and say in the same commit where that number came
from and how it was checked (CONTRIBUTING.md, "Reference numbers are verified
from raw").

DELIBERATELY NOT REGISTERED AS AN ANALYZER. `leakage_demonstration` is on the
process claim allowlist in model.py, which means `Guard.admit()` — correctly,
per its own rules — admits it under the DEFAULT profile with no gate at all
(only PERSON_CLAIM_TYPES are gated behind `person_inference` + an owner
token). If this function were wired in as a normal analyzer via
`@register(...)` and imported into `analyze/__init__.py`, it would run on
every `corpuslens run` against every ordinary corpus — exactly the outcome
this task was told to avoid. It is also structurally unfit for that registry:
analyzers receive `events: list[Event]`, and an `Event` never carries an
absolute timestamp (that is the wall's whole point), so there is nothing for
it to compute over there. The only honest inputs are timestamps the owner
supplies directly, from a file they name — which is a different shape of
command than "an analyzer that runs over this run's Events", and building
that command (`corpuslens fingerprint <file>`, per IDEAS.md) is the part of
this feature that is still genuinely unresolved: doing so needs the CLI to
construct some non-default profile or capability for a `Guard`-free,
owner-named-file command, and `cli.py`'s docstring states there is
deliberately no CLI flag that grants a capability. This module does not
resolve that collision. See NOTES-leakage-demo.md for the open design
options.
"""
from __future__ import annotations

import datetime as _dt
import math
import statistics
from typing import Optional, Sequence, Union

HOUR_S = 3600.0
DAY_S = 86400.0
HOURS_PER_WEEK = 24 * 7          # the histogram's bin count
MAX_LAG_DAYS = 28                # cap the autocorrelation search; four weeks of context


TimestampLike = Union[int, float, _dt.datetime]


def _to_epoch_seconds(t: TimestampLike) -> float:
    """Accept a raw epoch-seconds number or a `datetime`. A naive `datetime` is
    interpreted via its own `.timestamp()` (platform local time) — this
    function does not adjudicate timezones; pass timezone-aware datetimes, or
    raw epoch seconds, if that distinction matters for your input."""
    if isinstance(t, _dt.datetime):
        return t.timestamp()
    return float(t)


def _autocorr(series: Sequence[float], lag: int) -> Optional[float]:
    """Pearson autocorrelation of `series` against itself shifted by `lag`
    steps. None where it is not computable (too short, or one side constant —
    `statistics.correlation` requires nonzero variance on both sides)."""
    if lag <= 0 or lag >= len(series):
        return None
    a, b = series[:-lag], series[lag:]
    if len(a) < 2:
        return None
    try:
        return statistics.correlation(a, b)
    except statistics.StatisticsError:
        return None


def timing_fingerprint(timestamps: Sequence[TimestampLike]) -> dict:
    """Report how re-identifying the TIMING SHAPE of `timestamps` is — never
    the schedule itself. See the module docstring for the full contract:
    what is reported, what is never reported, the method and its limits, and
    why no safe/unsafe verdict is computed.

    `timestamps` — any sequence of absolute timestamps the caller already
    holds in the clear (epoch seconds, or `datetime` objects). Order does not
    matter; duplicates are allowed and counted.

    Returns a dict. On fewer than 2 usable timestamps, returns
    `{"n": <count>, "error": "<why>"}` — matching this project's existing
    analyzer error contract (see analyze/tempo.py) — with no other keys,
    because there is nothing to compute over one point or none.
    """
    values = [_to_epoch_seconds(t) for t in timestamps]
    n = len(values)
    if n < 2:
        return {"n": n, "error": "need at least 2 timestamps to measure periodicity or concentration"}

    ts = sorted(values)
    t0 = ts[0]

    # ---- concentration of the hour-of-week histogram ----
    bins = [0] * HOURS_PER_WEEK
    for t in ts:
        bucket = int((t - t0) // HOUR_S) % HOURS_PER_WEEK
        bins[bucket] += 1
    probs = [c / n for c in bins if c > 0]
    entropy_bits = -sum(p * math.log2(p) for p in probs)
    max_entropy_bits = math.log2(HOURS_PER_WEEK)
    bits_below_uniform = max_entropy_bits - entropy_bits

    # ---- whether a ~7-day period is present, and how strongly ----
    n_days = int((ts[-1] - t0) // DAY_S) + 1
    day_counts = [0] * n_days
    for t in ts:
        day_counts[int((t - t0) // DAY_S)] += 1

    weekly_autocorr = None
    autocorr_rank_pct = None
    max_lag = min(n_days - 1, MAX_LAG_DAYS)
    if max_lag >= 7:
        coeffs = {lag: _autocorr(day_counts, lag) for lag in range(1, max_lag + 1)}
        weekly_autocorr = coeffs.get(7)
        valid = [c for c in coeffs.values() if c is not None]
        if weekly_autocorr is not None and len(valid) > 1:
            at_or_below = sum(1 for c in valid if c <= weekly_autocorr)
            autocorr_rank_pct = round(100.0 * at_or_below / len(valid), 1)

    return {
        "n": n,
        "n_days_spanned": n_days,
        "hour_of_week_bins": HOURS_PER_WEEK,
        "hour_of_week_entropy_bits": round(entropy_bits, 3),
        "hour_of_week_max_entropy_bits": round(max_entropy_bits, 3),
        "hour_of_week_bits_below_uniform": round(bits_below_uniform, 3),
        "weekly_autocorr_lag7": round(weekly_autocorr, 3) if weekly_autocorr is not None else None,
        "weekly_autocorr_rank_pct": autocorr_rank_pct,
        "reading": (
            "hour_of_week_bits_below_uniform is roughly how many bits of schedule this file's "
            "timing carries: near 0 means the hours are spread evenly across the week (little to "
            "re-identify from timing alone), near hour_of_week_max_entropy_bits means the hours are "
            "concentrated into few weekly slots. weekly_autocorr_lag7 is a correlation coefficient "
            "(-1..1, None if n_days_spanned is too short to estimate): positive and high means a "
            "same-day-of-week rhythm repeats; near zero means this method finds none; negative means "
            "the count seven days later tends to run the opposite way. weekly_autocorr_rank_pct places "
            "it among this file's own other lags for context. These numbers are not a safety threshold "
            "— there is no verified cutoff separating an identifiable schedule from an anonymous one "
            "for this kind of file. Read the direction and the magnitude; do not read a verdict into "
            "them."
        ),
    }
