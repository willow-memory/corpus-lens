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
  * `hour_of_week_entropy_bits` / `hour_of_week_bits_below_uniform` — the RAW
    concentration of the 168-bin (24h x 7d) hour-of-week histogram, in bits.
    A uniform week carries `log2(168)` ~= 7.39 bits of entropy and zero bits
    "below uniform"; a schedule concentrated into a few hour-of-week slots
    carries entropy near zero and most of those ~7.39 bits "below uniform".
    THESE RAW NUMBERS ARE BIASED AND MUST NOT BE READ ON THEIR OWN — see
    SAMPLE-SIZE BIAS below. They are kept in the output for transparency
    (so a reader can see the plug-in number and the correction applied to
    it), never as the headline.
  * `hour_of_week_null_mean_bits_below_uniform` / `hour_of_week_bits_below_uniform_excess`
    — the bias correction. `..._excess` (raw minus the null baseline) is the
    number to read: "roughly how many bits of schedule this file carries
    ABOVE what n uniformly-random timestamps over the same span would show by
    chance alone." Near zero means what a reader will assume it means — no
    detectable weekly concentration — at ANY `n`, because the comparison is to
    chance at that same `n`, not to a fixed scale. See SAMPLE-SIZE BIAS.
  * `weekly_autocorr_lag7` / `weekly_autocorr_rank_pct` — whether a ~7-day
    period is present, and how strongly, as a continuous autocorrelation
    coefficient (see METHOD below) plus its rank among the other lags this
    same corpus could support. This is deliberately NOT collapsed into a
    present/absent boolean: a boolean needs a cutoff, and this project's rule
    is that a threshold is only added once it is defensible (see NO VERDICT).
  * `n_days_spanned` — context for how noisy the autocorrelation estimate is
    (a 10-day corpus cannot support a confident lag-7 read).

SAMPLE-SIZE BIAS IN THE HOUR-OF-WEEK ESTIMATE, AND THE FIX (found in review,
2026-09-11: 12 uniformly random timestamps over 8 weeks — no schedule at all —
plug-in-reported 3.974 "bits below uniform" out of a 7.392 maximum; the same
generator at n=4000 reported 0.033). The plug-in Shannon entropy estimator
used on `hour_of_week_entropy_bits` is a biased estimator of the true entropy
whenever `n` is not large relative to the bin count (168): with few samples,
most of the 168 bins sit empty not because the underlying process avoids
them, but because there weren't enough draws to reach them, and the estimator
cannot tell "structurally empty" from "just never sampled" apart. A short
observed SPAN compounds this: if the data covers only a few days, most of the
168 hour-of-week bins are literally unreachable in that window regardless of
how the events within it are distributed, which looks identical to a real
weekly schedule to the plug-in estimator. Miller-Madow does not rescue this
at these sample sizes (at n=12 against 168 bins the correction is ~0.66 bits
against a ~4-bit error) — the fix here instead measures the bias directly:
`_null_bits_below_uniform_stats()` runs a small, seeded Monte Carlo (see
`NULL_TRIALS` / `NULL_SEED` — fixed, so a given `(n, span)` always reproduces
the same null estimate) simulating `n` UNIFORMLY RANDOM timestamps over the
SAME observed span, computes `bits_below_uniform` for each trial the same way
the real data is scored, and reports the mean as the noise floor. The excess
over that floor is the headline. Where the noise floor alone already accounts
for at least half of the theoretical maximum (`NULL_UNRELIABLE_FRACTION`),
the estimate cannot distinguish a real weekly pattern from an artifact of
`n` and span at all, and `timing_fingerprint()` refuses that half of the
report (an `"error"` field, in addition to whatever else is still
computable — see the docstring on `timing_fingerprint()`) rather than publish
a number that would mean nothing. This is a computability gate on whether the
STATISTIC can be estimated at this `n`, not a privacy verdict on the DATA —
see NO VERDICT below for why those are different things and only one of them
is refused elsewhere on purpose.

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
from raw"). `NULL_UNRELIABLE_FRACTION`, above, is NOT such a threshold and
must not be treated as the door left open for one: it governs only whether
the entropy ESTIMATOR has enough signal at this `n`/span to report a number
at all (a statistical-power question with a mechanical, checkable answer —
"would pure chance already produce most of this reading?"), never whether
the resulting number means the file is safe to share.

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
import random
import statistics
from typing import Optional, Sequence, Union

HOUR_S = 3600.0
DAY_S = 86400.0
HOURS_PER_WEEK = 24 * 7  # the histogram's bin count
MAX_LAG_DAYS = 28  # cap the autocorrelation search; four weeks of context

# Sample-size-bias correction (see module docstring, SAMPLE-SIZE BIAS). The
# null is a seeded Monte Carlo, not the caller's global `random` state, so a
# given (n, span) always reproduces the same baseline and calling this
# function never disturbs randomness anywhere else in the process.
NULL_TRIALS = 200  # simulated draws averaged into the null baseline
NULL_SEED = 0xC0FFEE  # fixed: reproducibility, not secrecy
# If pure chance, at this n and span, already accounts for at least this
# fraction of the theoretical maximum "bits below uniform", the estimator
# cannot tell a real weekly pattern from that noise floor at all — refuse
# rather than publish a number that would not mean what it looks like it
# means. A statistical-power gate, not a privacy verdict — see NO VERDICT.
NULL_UNRELIABLE_FRACTION = 0.5


TimestampLike = Union[int, float, _dt.datetime]


def _to_epoch_seconds(t: TimestampLike) -> float:
    """Accept a raw epoch-seconds number or a `datetime`. A naive `datetime` is
    interpreted via its own `.timestamp()` (platform local time) — this
    function does not adjudicate timezones; pass timezone-aware datetimes, or
    raw epoch seconds, if that distinction matters for your input."""
    if isinstance(t, _dt.datetime):
        return t.timestamp()
    return float(t)


def _hour_of_week_entropy_bits(offsets_s: Sequence[float]) -> float:
    """Plug-in Shannon entropy, in bits, of the 168-bin hour-of-week histogram
    built from `offsets_s` (seconds since SOME reference point — the caller
    decides what that point is; only differences among `offsets_s` matter).
    This is the biased estimator described in the module docstring's
    SAMPLE-SIZE BIAS section — callers must correct it against
    `_null_bits_below_uniform_stats()` before reporting it as a finding."""
    n = len(offsets_s)
    bins = [0] * HOURS_PER_WEEK
    for t in offsets_s:
        bins[int(t // HOUR_S) % HOURS_PER_WEEK] += 1
    probs = [c / n for c in bins if c > 0]
    return -sum(p * math.log2(p) for p in probs)


def _null_bits_below_uniform_stats(
    n: int, span_s: float, trials: int = NULL_TRIALS, seed: int = NULL_SEED
) -> tuple:
    """Monte Carlo noise floor for `hour_of_week_bits_below_uniform` at this
    exact `n` and observed `span_s`: `trials` runs of `n` UNIFORMLY RANDOM
    offsets drawn from `[0, span_s)` — no schedule whatsoever — scored the
    same way the real data is scored. Returns `(mean, stdev)`. Seeded with a
    private `random.Random` instance (never the module-global `random` state)
    so this is reproducible and side-effect-free: the same `(n, span_s)`
    always returns the same baseline, and calling it never perturbs any other
    caller's randomness.

    `span_s == 0` (every timestamp identical) is degenerate but harmless:
    every simulated draw lands in bin 0 too, so the null is exactly zero —
    the real data's own `bits_below_uniform` will also be exactly zero, and
    the excess correctly comes out to zero rather than undefined.
    """
    rng = random.Random(seed)
    max_entropy_bits = math.log2(HOURS_PER_WEEK)
    deficits = []
    for _ in range(trials):
        offsets = [rng.uniform(0.0, span_s) for _ in range(n)]
        deficits.append(max_entropy_bits - _hour_of_week_entropy_bits(offsets))
    mean = statistics.mean(deficits)
    stdev = statistics.stdev(deficits) if len(deficits) > 1 else 0.0
    return mean, stdev


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

    On 2+ timestamps where n and span are too small for the hour-of-week
    estimator to have any signal (see module docstring, SAMPLE-SIZE BIAS),
    the full dict is still returned — including the (unaffected)
    `weekly_autocorr_lag7` fields — but
    `hour_of_week_bits_below_uniform_excess` is `None` and an `"error"` key
    explains why, rather than a biased number being reported as a finding.
    """
    values = [_to_epoch_seconds(t) for t in timestamps]
    n = len(values)
    if n < 2:
        return {
            "n": n,
            "error": "need at least 2 timestamps to measure periodicity or concentration",
        }

    ts = sorted(values)
    t0 = ts[0]
    offsets = [t - t0 for t in ts]
    span_s = offsets[-1]  # 0.0 when every timestamp is identical

    # ---- concentration of the hour-of-week histogram, bias-corrected ----
    # `entropy_bits` / `bits_below_uniform` are the RAW plug-in estimator and
    # are biased upward whenever n is not large relative to 168 bins, or the
    # span is short relative to a week — see module docstring, SAMPLE-SIZE
    # BIAS. `null_mean` is what n uniformly-random timestamps over this same
    # span would produce by chance alone (seeded Monte Carlo, reproducible);
    # `excess` (raw minus that floor) is the number meant to be read.
    max_entropy_bits = math.log2(HOURS_PER_WEEK)
    entropy_bits = _hour_of_week_entropy_bits(offsets)
    bits_below_uniform = max_entropy_bits - entropy_bits
    null_mean, null_stdev = _null_bits_below_uniform_stats(n, span_s)
    excess = bits_below_uniform - null_mean

    concentration_unreliable = (
        max_entropy_bits > 0 and null_mean >= NULL_UNRELIABLE_FRACTION * max_entropy_bits
    )

    # ---- whether a ~7-day period is present, and how strongly ----
    n_days = int(span_s // DAY_S) + 1
    day_counts = [0] * n_days
    for o in offsets:
        day_counts[int(o // DAY_S)] += 1

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

    result = {
        "n": n,
        "n_days_spanned": n_days,
        "hour_of_week_bins": HOURS_PER_WEEK,
        "hour_of_week_entropy_bits": round(entropy_bits, 3),
        "hour_of_week_max_entropy_bits": round(max_entropy_bits, 3),
        "hour_of_week_bits_below_uniform": round(bits_below_uniform, 3),
        "hour_of_week_null_mean_bits_below_uniform": round(null_mean, 3),
        "hour_of_week_null_trials": NULL_TRIALS,
        "hour_of_week_bits_below_uniform_excess": (
            None if concentration_unreliable else round(excess, 3)
        ),
        "weekly_autocorr_lag7": round(weekly_autocorr, 3) if weekly_autocorr is not None else None,
        "weekly_autocorr_rank_pct": autocorr_rank_pct,
        "reading": (
            "hour_of_week_bits_below_uniform_excess is roughly how many bits of schedule this "
            "file's timing carries ABOVE what n timestamps drawn uniformly at random over the same "
            "span would show by chance (hour_of_week_null_mean_bits_below_uniform is that chance "
            "level, hour_of_week_bits_below_uniform is the raw, uncorrected reading — kept for "
            "transparency, not for reading on its own). Excess near zero means no detectable weekly "
            "concentration, at any n. weekly_autocorr_lag7 is a correlation coefficient (-1..1, None "
            "if n_days_spanned is too short to estimate): positive and high means a same-day-of-week "
            "rhythm repeats; near zero means this method finds none; negative means the count seven "
            "days later tends to run the opposite way. weekly_autocorr_rank_pct places it among this "
            "file's own other lags for context. These are not a safety threshold — there is no "
            "verified cutoff separating an identifiable schedule from an anonymous one for this kind "
            "of file. Read the direction and the magnitude; do not read a verdict into them."
        ),
    }
    if concentration_unreliable:
        result["error"] = (
            f"hour_of_week_bits_below_uniform_excess is not reported: at n={n} over this span, "
            f"{NULL_TRIALS} simulated draws of n uniformly random (schedule-free) timestamps over "
            f"the same span already produce a mean of {round(null_mean, 3)} bits below uniform — at "
            f"least {int(NULL_UNRELIABLE_FRACTION * 100)}% of the {round(max_entropy_bits, 3)}-bit "
            f"maximum — so this estimator cannot tell a real weekly pattern from pure chance at this "
            f"n. More timestamps, or a longer span, are needed before this number means anything. "
            f"weekly_autocorr_lag7 below is unaffected — it uses a different method with its own "
            f"stated span requirement."
        )
    return result
