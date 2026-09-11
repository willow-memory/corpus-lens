"""Share mode: coarsen an already-computed report for someone to paste
somewhere other than their own machine.

Per IDEAS.md ("A share mode for the report", Near): the README's own founding
observation is that timing shape re-identifies a person even with content
stripped, and a full report carries thread counts, day spans, tempo quantiles
and a concurrency peak — enough that pasting one into a public issue is a
small version of the thing the wall exists to prevent. This module is the
coarsening step: headline rates only, each denominator's `n` rounded to a wide
band, and no shape figures at all.

**This is the first output this tool has that is *meant* to leave the
machine** — every other output is meant to stay local. That makes it more
load-bearing than it looks, not less: say the wrong thing about it once, in a
docstring or a CLI help string, and it is quoted forever.

**What this module does NOT claim, on purpose (never say otherwise):**
  * NOT anonymous. NOT de-identified. NOT safe to publish. Those are the
    exact words CONTRIBUTING.md forbids for this feature, because the
    re-identification question is explicitly unmeasured — see IDEAS.md,
    "Population reference points without pooling anyone's corpus". This
    module only removes fields; it has no way to know whether what remains
    still fingerprints its owner, especially at small `n`.
  * NOT a step that makes pooling several people's share output safe. It is
    named in IDEAS.md as a *candidate object* for that open question, not an
    answer to it: "it does not answer the re-identification question ... it
    just makes the object the question is about exist."
  * NOT a replacement for judgment. A human still decides whether to paste
    this anywhere, same as before — this just narrows what there is to paste.

THE RULE THIS MODULE HOLDS (fail-closed, same posture as the Guard): a field
survives coarsening only if its name is on `RATE_FIELDS` below. A field a
future analyzer invents is, by construction, not on a list written before
that analyzer existed — so it is coarsened away by default, not leaked by
default. Extending RATE_FIELDS is a deliberate, reviewable, one-line act; the
default for everything else is exclusion, never inclusion.

TWO THINGS GET COARSENED, NOT ONE: `coarsen()` (below) handles each
analyzer's own numbers; `coarsen_audit()` handles the audit record's exact
`n_events` / `n_dropped` / `n_filtered` the same way. Both matter — an audit
sentence that still says "This run read 21 events (dropped 0...)" gives away
the exact corpus size and exact drop count even when every analyzer's `n` is
a band, and that is the same class of quantity the banding exists to blur.
"""
from __future__ import annotations

import dataclasses

# Percentage fields that are genuine RATES over their analyzer's declared
# denominator, reviewed one at a time. Adding a name here is a claim that the
# field is a rate, not a shape statistic wearing a percent sign — say why in
# the comment.
#
# Deliberately NOT on this list, even though every one of them is a "_pct"
# field that would pass a naive "ends in _pct" filter:
#   - single_turn_sessions_pct (steering_density) and
#     single_day_threads_pct (thread_span) describe the SHAPE of a
#     distribution (how many sessions/threads are exactly one unit long),
#     not a plain rate over the analyzer's headline denominator.
#   - burst_pct / resumed_pct (tempo) are a two-bucket histogram of the same
#     censored inter-turn gaps that produce the tempo quantiles this feature
#     exists to withhold — bucketing a timing distribution two ways instead
#     of four does not stop it from being a timing distribution.
# When a field's status is genuinely unclear, it stays off this list — see
# CONTRIBUTING.md ("classifiers undercount, never overclaim") and the
# instruction in IDEAS.md that under-sharing is the correct direction of
# error here.
RATE_FIELDS = frozenset({
    "mid_task_share_pct",       # steering_density's own headline rate
    "authored_code_pct",        # composition_mix
    "code_ref_pct",              # composition_mix
    "delib_pct",                 # composition_mix
    "clarification_forks_pct",  # clarification_pull
    "delta_coverage_pct",       # tempo — measurability, not the gap shape
})

# Wide bands for a denominator's size. Never an exact count.
_N_BANDS = (30, 100, 1000, 10000, 100000)


def band_n(n) -> str:
    """A denominator size, coarsened to a wide band — never the exact count.
    `n < 30` reads as `<30` (the same threshold the full report already
    labels as SMALL_N); above the top band reads as `100000+`."""
    if not isinstance(n, (int, float)) or isinstance(n, bool) or n < 0:
        return "unknown"
    if n < _N_BANDS[0]:
        return f"<{_N_BANDS[0]}"
    for lo, hi in zip(_N_BANDS, _N_BANDS[1:]):
        if lo <= n < hi:
            return f"{lo}-{hi}"
    return f"{_N_BANDS[-1]}+"


def _headline(safe_fields: dict) -> str:
    """Built ONLY from field names and numbers already on the allowlist —
    never from an analyzer's own free-text `headline`/`reading`, which is how
    thread_shape, tempo and thread_span leak a median gap or a concurrency
    peak straight into prose in the full report. A name and a number cannot
    smuggle a sentence's worth of shape the way a paragraph can."""
    if not safe_fields:
        return ("No share-safe rate for this analyzer: every value it returned "
                "is a shape rather than a plain rate, and share mode omits it "
                "by default, not just rounds it.")
    parts = ", ".join(f"{k} {v}%" for k, v in sorted(safe_fields.items()))
    return f"Share-safe rate(s): {parts}."


def coarsen_result(res: dict) -> dict:
    """One analyzer's result dict, coarsened. Fail-closed: nothing survives
    unless it is explicitly recognised below — an unrecognised field, whether
    from an analyzer already in this codebase or one added tomorrow, is
    dropped, not passed through."""
    if "error" in res:
        # Not computable is not a shape to hide — say so, same message as the
        # full report, since the message itself is a fixed string, never
        # corpus content.
        out = {"error": res["error"]}
        if res.get("denominator"):
            out["denominator"] = res["denominator"]
        return out
    out = {}
    if res.get("denominator"):
        out["denominator"] = res["denominator"]
    n = res.get("n")
    if isinstance(n, int) and not isinstance(n, bool):
        out["n_band"] = band_n(n)
    safe = {k: v for k, v in res.items()
            if k in RATE_FIELDS and isinstance(v, (int, float)) and not isinstance(v, bool)}
    out.update(safe)
    out["headline"] = _headline(safe)
    return out


def coarsen(results: dict) -> dict:
    """A full `run` results dict (analyzer name -> result), coarsened
    analyzer by analyzer. Order and analyzer set are preserved; only each
    analyzer's OWN fields are filtered."""
    return {name: coarsen_result(res) for name, res in results.items()}


def coarsen_audit(audit):
    """A copy of a `guard.AuditRecord` with `n_events`, `n_dropped` and
    `n_filtered` replaced by wide bands (`band_n`) instead of exact counts.

    FOUND BY REVIEW: the audit sentence names exactly what left the wall, and
    that stays required in share mode — but the FIRST version of this module
    coarsened analyzer results only, while `guard.AuditRecord.sentence()` and
    `.as_dict()` kept printing the corpus's exact event count and exact drop
    count in plain language ("This run read 21 events..."). Exact corpus size
    and exact drop count are the same class of quantity `band_n` exists to
    blur for every analyzer's `n` — rounding one and publishing the other
    made the report merely LOOK coarsened.

    This returns a NEW record via `dataclasses.replace` rather than mutating
    the one the run is using — `sentence()` and `as_dict()` are both plain
    functions of `self`'s fields, so calling them on this copy is the ONLY
    code path that produces either; there is no second, separately-written
    sentence to drift out of sync with the fields (or with a future edit to
    `sentence()`'s wording).

    Same reasoning covers `discovered_path`: it is set only when `corpuslens
    run` was given no path/--adapter and found the corpus itself under the
    owner's home directory (see cli.py's zero-config discovery), and a home
    path can carry the owner's username. That is exactly the class of
    machine-identifying detail share mode exists to omit, so it is dropped
    here rather than carried into an output meant to leave the machine —
    never rounded, never partially shown, gone."""
    return dataclasses.replace(
        audit,
        n_events=band_n(audit.n_events),
        n_dropped=band_n(audit.n_dropped),
        n_filtered=band_n(audit.n_filtered),
        discovered_path=None,
    )
