"""corpuslens.guard — THE WALL.

Sits between ingestion and analysis. Four mechanisms in the spine:

  1. Quarantine custody: the calendar anchor, timezone, and the filename->line
     map are held privately by the Guard; `release()` is the supported door
     and it fail-closes on every path.
  2. Capability profile: the default profile grants NOTHING. Absolute calendar
     position, timezone, and person-shaped claims are all off by default.
  3. Claim gate: an analyzer whose declared claims are not on the process
     allowlist does not register. Unknown claim -> refusal (fail closed).
  4. Audit: every run produces a plain-language record of what ran, what was
     granted, and what was denied — a sentence a family can read.

WHAT THE WALL GUARANTEES, STATED HONESTLY (corrected after review). The wall
keeps the ABSOLUTE ANCHOR — which real date is day 0, which timezone, which
clock hour, and the raw filenames (which embed both) — out of the data an
analyzer receives. Recovering a real calendar date, weekday label, or hour
requires re-supplying the anchor through this Guard, with a capability + owner
token + logged justification.

WHAT IT DOES NOT DO, ALSO STATED HONESTLY:
  * It does not hide weekly *cadence*. `day_offset % 7` preserves the shape of
    a week up to one unknown rotation; that is inherent to relative-day data
    and cannot be walled off while still computing resumption/concurrency.
  * It does not fully hide *within-day time-of-day*. Cross-midnight deltas are
    censored (so the clock cannot be pinned at a day boundary), but the deltas
    within a single day survive for tempo analysis, and their cumulative span
    loosely BOUNDS the local time-of-day on a day one thread spans for many
    hours (e.g. a 21-hour span forces the first event before ~03:00 local).
    This is a weak local-clock bound — never the timezone, never the date —
    and we disclose it rather than claim an absolute "no clock hour" wall.
  * It is not an adversarial sandbox against the machine's OWNER. This is a
    local tool you run on your own logs to study yourself; a determined owner
    can always read their own quarantined data by editing their own script.
    The wall's job is to stop ACCIDENTAL leaks and to constrain analyzer
    PLUGINS — the default, supported path emits process only. Claiming it
    stops the owner would itself be the overclaim this project forbids.

If a *plugin analyzer running the supported path* can recover the absolute
anchor, that is a bug of the highest class: report it like one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .egress_shapes import find_structural_leaks
from .model import PERSON_CLAIM_TYPES, PROCESS_CLAIM_TYPES, Quarantine
from .share_shape import find_shape_violations


class WallError(Exception):
    """A hard stop at the wall. Never swallowed."""


@dataclass(frozen=True)
class Profile:
    """Capabilities granted for a run. Default: nothing."""
    name: str = "default"
    capabilities: frozenset = frozenset()
    owner_token: Optional[str] = None   # required for any person-class release

    def grants(self, cap: str) -> bool:
        return cap in self.capabilities


DEFAULT_PROFILE = Profile()

# Capabilities that exist in the spine. Adding one is a design act.
KNOWN_CAPABILITIES = frozenset({
    "calendar_time",     # release the base date (turns day_offset into dates)
    "local_tz",          # release the timezone
    "person_inference",  # allow PERSON_CLAIM_TYPES analyzers to register
})


@dataclass
class AuditRecord:
    profile: str
    granted: list = field(default_factory=list)
    denied: list = field(default_factory=list)
    analyzers_run: list = field(default_factory=list)
    analyzers_refused: list = field(default_factory=list)
    n_events: int = 0
    n_dropped: int = 0
    adapter: Optional[str] = None
    # Set only when `corpuslens run` was given no path/--adapter and chose this
    # corpus itself (see cli.py's zero-config discovery). None for every
    # explicit-path run, which is the overwhelming majority of runs and whose
    # sentence must read exactly as it always has. Discovery is a GUESS about
    # intent standing in for something the user did not type, so unlike an
    # explicit path (which is already in the user's own command line) this one
    # has to appear in the report itself, not just a terminal preamble that
    # vanishes once the report is written to --out and read later on its own —
    # see NOTES-zeroconf.md for the reasoning.
    #
    # MUST BE THE ADAPTER'S DECLARED CONVENTIONAL FORM ONLY (e.g.
    # '~/.claude/projects', straight from `ingest.default_path_of`) — NEVER a
    # resolved absolute path. A resolved path under $HOME embeds the owner's
    # real username, which is exactly the class of thing this project
    # quarantines a filename for (model.py) and hashes a db path for
    # (_rows.py::assemble): "This resolved home directory IS that, with the
    # username right there in it" (review finding, highest class — a prior
    # version of this feature reported the resolved path and put a real name
    # in the same sentence that claims nothing identifying left the wall).
    # `__setattr__` below enforces this at assignment time, not just by
    # convention, because the leak happened via a plain attribute set
    # (`guard.audit.discovered_path = path`) that a docstring alone would not
    # have stopped.
    discovered_path: Optional[str] = None
    filters: list = field(default_factory=list)   # human-readable filter clauses
    n_filtered: int = 0                            # events excluded BY those filters
    # Set by `cli.run()` from `subject.infer_subject()` — one of
    # `subject.SUBJECTS` ("human"/"agent"/"mixed"/"unknown"), or `None` when
    # nothing set it (every direct construction of an AuditRecord outside the
    # real pipeline — most of this project's own tests included). `guard.py`
    # deliberately does not import `corpuslens.subject` or know what an
    # "authorship classifier" is; it only carries the belief and states its
    # own fallibility in `sentence()` below. See corpuslens/subject.py for
    # what derives this value and why it is never a CLI flag.
    subject: Optional[str] = None
    subject_reason: Optional[str] = None
    # Set by `cli.run()`/`cli.doctor()` ONLY when the operator named a subject
    # who is not the owner (`--subject`) and that subject's consent grant was
    # verified BEFORE anything was read — see corpuslens/subject_consent.py.
    # Holds the scope that was verified (e.g. "process_analysis"), never the
    # subject's identifier: the sentence that says nothing identifying left
    # the wall must not carry a person's id, even an opaque one. None on every
    # run without `--subject`, i.e. every owner == subject run, whose sentence
    # must read exactly as it always has.
    subject_consent: Optional[str] = None

    def __setattr__(self, name: str, value) -> None:
        """Fail closed on the one field that must never carry a resolved
        path: `discovered_path` is `None` or starts with `~` (the adapter's
        declared, unexpanded convention), full stop. Overriding `__setattr__`
        rather than trusting `__post_init__` matters here because the actual
        leak this guards was a plain attribute assignment AFTER construction
        (`guard.audit.discovered_path = path` in cli.py), not something a
        constructor-only check would have caught — every assignment, at
        construction or later, goes through this."""
        if name == "discovered_path" and value is not None and not str(value).startswith("~"):
            raise WallError(
                "AuditRecord.discovered_path must be the adapter's DECLARED "
                "conventional location (e.g. '~/.claude/projects', from "
                "ingest.default_path_of) — never a resolved absolute path. A "
                "resolved path under $HOME carries the owner's real username into "
                "the audit sentence and JSON output; that is precisely the leak "
                "this field exists to prevent, not cause."
            )
        object.__setattr__(self, name, value)

    def as_dict(self) -> dict:
        """The audit record as structured data — for the JSON renderer. Carries
        the plain-language sentence too: a machine-readable result must not be a
        way to get the numbers without the statement of what left the wall."""
        return {
            "profile": self.profile,
            "adapter": self.adapter,
            "discovered_path": self.discovered_path,
            "granted": list(self.granted),
            "denied": list(self.denied),
            "analyzers_run": list(self.analyzers_run),
            "analyzers_refused": list(self.analyzers_refused),
            "n_events": self.n_events,
            "n_dropped": self.n_dropped,
            "filters": list(self.filters),
            "n_filtered": self.n_filtered,
            "subject": self.subject,
            "subject_reason": self.subject_reason,
            "subject_consent": self.subject_consent,
            "sentence": self.sentence(),
        }

    # Human-readable label for each `subject.SUBJECTS` value, spliced into the
    # clause below. Deliberately says what corpuslens BELIEVES, not what the
    # corpus IS — every phrase here stays true even when the classifier that
    # produced it is wrong, because none of them assert the underlying fact,
    # only the belief and its evidence.
    _SUBJECT_LABELS = {
        "human": "human",
        "agent": "agent, not human",
        "mixed": "a mix of human and agent, not one human",
        "unknown": "of undetermined authorship",
    }

    def sentence(self) -> str:
        g = ", ".join(self.granted) or "nothing beyond process analysis"
        r = f"; refused: {', '.join(self.analyzers_refused)}" if self.analyzers_refused else ""
        disco = ""
        if self.discovered_path:
            # No path or --adapter was typed this run — the tool guessed, so
            # the guess belongs in the same sentence the adapter name already
            # lives in, not just in a terminal message the reader of a saved
            # report will never see.
            disco = (f"No path or --adapter was given: corpuslens discovered this corpus "
                     f"itself at {self.discovered_path}, using the '{self.adapter}' adapter. ")
        f = ""
        if self.filters:
            # a filtered run analyzes a SUBSET — say so, and say how big the cut was,
            # so no number below is mistaken for a whole-corpus number.
            f = (f"This run was filtered ({'; '.join(self.filters)}): {self.n_filtered} further "
                 f"event(s) fell outside the window and are excluded from every number below, "
                 f"so these are subset numbers, not corpus numbers. ")
        base = (disco + f
                + f"This run read {self.n_events} events (dropped {self.n_dropped}, counted not hidden), "
                f"ran {len(self.analyzers_run)} process analyzers under profile '{self.profile}', "
                f"and was granted {g}{r}. ")
        if self.granted:
            # a capability was released this run — do NOT claim nothing left the wall
            tail = ("Because the capability(ies) named above were granted, the corresponding "
                    "quarantined value(s) — calendar anchor, timezone, and/or filename — WERE "
                    "released under owner grant: this run is not anchor-free. Relative day and "
                    "within-day tempo also left the wall.")
        else:
            tail = ("No absolute calendar date, timezone, or filename left the wall; relative day "
                    "and within-day tempo did — these preserve weekly cadence, and on a day a single "
                    "thread spans for many hours they loosely bound the local time-of-day (never the "
                    "timezone or the date).")
        subj = ""
        if self.subject is not None:
            # WHAT LEFT THE WALL is not the only thing worth disclosing: every
            # headline below is written in the second person, and every
            # reference table compares the reader to a HUMAN's corpus. Both of
            # those are claims about WHO the operator role is, and this run
            # never verified that — it inferred it, from a classifier that can
            # be wrong. State the belief and its own fallibility in the same
            # breath, so this clause stays true whether or not the classifier
            # guessed right: it is a claim about what corpuslens BELIEVES,
            # never a claim about who actually typed a turn.
            label = self._SUBJECT_LABELS.get(self.subject, self.subject)
            reason = self.subject_reason or "no reason recorded"
            subj = (f" This run's authorship classifier reads the operator-role turns as "
                    f"{label} ({reason}) — an inferred belief, not a verified fact, and it can "
                    f"be wrong; nothing in this report proves who actually typed a turn, and "
                    f"every 'you'/'your' below should be read as shorthand for that belief.")
        consent = ""
        if self.subject_consent:
            # owner != subject: say that the corpus is someone else's, that
            # their grant was verified before it was opened, and that the run
            # is on their record — without naming them. The default (owner ==
            # subject) adds nothing, so every existing sentence is unchanged.
            consent = (f" This corpus was analyzed as another person's, not the operator's: a "
                       f"verified consent grant for the '{self.subject_consent}' scope was "
                       f"found for that subject before anything was read, and this run was "
                       f"appended to the subject's own disclosure record. The subject's "
                       f"identifier is not in this report.")
        return base + tail + subj + consent


class Guard:
    """Holds the Quarantine privately (name-mangled) so the supported way to
    reach an anchored value is `release()`. This makes accidental access loud;
    it is not, and does not claim to be, unbypassable by the owner."""

    def __init__(self, quarantine: Quarantine, profile: Profile = DEFAULT_PROFILE):
        self.__q = quarantine          # name-mangled: not a casual public field
        self.profile = profile
        self.audit = AuditRecord(profile=profile.name)
        self._released_caps: set = set()   # caps actually released this run (egress scan)

    # ── quarantine custody ───────────────────────────────────────────────
    def release(self, cap: str, justification: str) -> object:
        """The supported door to quarantined values. Fail-closed on every path:
        unknown capability, ungranted capability, missing justification,
        or an anchor release without an owner token."""
        if cap not in KNOWN_CAPABILITIES:
            self.audit.denied.append(cap)
            raise WallError(f"unknown capability {cap!r} — absence of policy is denial")
        if not justification or not justification.strip():
            self.audit.denied.append(cap)
            raise WallError(f"capability {cap!r} requires a logged justification")
        if not self.profile.grants(cap):
            self.audit.denied.append(cap)
            raise WallError(f"capability {cap!r} not granted by profile {self.profile.name!r}")
        if cap in ("calendar_time", "local_tz") and self.profile.owner_token is None:
            self.audit.denied.append(cap)
            raise WallError(f"capability {cap!r} requires an owner token — a name is not an identity")
        self.audit.granted.append(f"{cap} ({justification.strip()})")
        self._released_caps.add(cap)
        if cap == "calendar_time":
            return self.__q.base_date_iso
        if cap == "local_tz":
            return self.__q.local_tz
        return True

    def resolve_ref(self, opaque_ref: str, justification: str) -> str:
        """Re-derive a real 'filename:line' from an Event's opaque source_ref —
        gated exactly like calendar_time, because filenames embed dates/names."""
        val = self.release("calendar_time", f"resolve_ref: {justification}")  # noqa: F841
        return self.__q.ref_map.get(opaque_ref, "")

    def scan_egress(self, text: str) -> str:
        """Defense-in-depth backstop at the OUTPUT choke point. The wall keeps
        the absolute anchor out of Events upstream; this re-reads the rendered
        report right before it leaves and refuses to emit if a quarantined value
        that was NOT released this run appears in it verbatim. It cannot make
        output safe on its own — it turns the accidental leak the upstream wall
        was supposed to prevent from a silent escape into a hard stop.

        Grant-aware: a value released under an owner grant is allowed to appear
        (the audit sentence already declares the run 'not anchor-free'), so only
        quarantined classes whose capability was NOT released are forbidden.

        The raised error never echoes the leaked value — a hard stop without
        payload, so the scan itself does not become the leak (returns the text
        unchanged when clean, so it can wrap the emit inline)."""
        q = self.__q
        forbidden: list = []
        if "calendar_time" not in self._released_caps:
            if q.base_date_iso:
                forbidden.append(("calendar anchor", str(q.base_date_iso)))
            # filenames embed dates/names and are gated by calendar_time (resolve_ref)
            for real_ref in q.ref_map.values():
                if real_ref:
                    forbidden.append(("filename", str(real_ref)))
        if "local_tz" not in self._released_caps and q.local_tz:
            forbidden.append(("timezone", str(q.local_tz)))
        for label, literal in forbidden:
            if literal and literal in text:
                raise WallError(
                    f"egress scan: a quarantined {label} appears in the outbound "
                    "report but its capability was not released this run — refusing "
                    "to emit. The upstream wall was bypassed; this is a highest-class "
                    "bug, report it like one.")
        # Second phase: shapes, not literals. The loop above can only see values
        # that were quarantined; a value that was never quarantined is invisible
        # to it by construction, which is precisely how the `discovered_path`
        # leak reached output. See egress_shapes.py for why this is not a
        # duplicate of the check above, and what it does not claim.
        shapes = find_structural_leaks(text, self._released_caps)
        if shapes:
            raise WallError(
                f"egress scan: the outbound report contains {', '.join(shapes)} — "
                "a shape the wall promises is not there, and no capability "
                "released this run accounts for it. Refusing to emit. This value "
                "was never quarantined, so the literal scan could not see it; "
                "that is a highest-class bug, report it like one.")
        return text

    def scan_share_shape(self, results: dict, audit_dict: dict) -> None:
        """The second, distinct check `DESIGN-guard-extraction.md` (2a) names
        as missing: a schema/shape assertion on the COARSENED share payload,
        run on the structured dict BEFORE it is rendered to text — distinct
        from `scan_egress`, which only ever sees rendered text and can only
        ask whether a quarantined literal or shape appears in it. Neither
        phase of `scan_egress` has any concept of "this field is not
        allowlisted" or "this denominator is an exact count, not a band" —
        that gap is real and was hit in production (see the audit note in
        `DESIGN-guard-extraction.md` §2a: a first share-mode implementation
        banded every analyzer's `n` but still published the corpus's exact
        `n_events`, and `scan_egress` passed it cleanly, because an exact `n`
        is neither a quarantined literal nor a recognizable structural
        shape).

        Delegates the actual check to `share_shape.find_shape_violations`,
        which is pure and returns violation LABELS only — this method's only
        job is the same one `scan_egress` already does for its own findings:
        raise, so a caller cannot compute a verdict and then forget to act on
        it. The raised error names the violated fields, never a payload
        value, matching every other error this module raises.

        THIS DOES NOT VERIFY THE COARSENED VALUES ARE SAFE TO PUBLISH — only
        that the coarsening step ran and produced the expected shape (every
        field allowlisted, every denominator a band). See `share_shape.py`'s
        module docstring and `share.py`'s for what neither this check nor
        share mode itself claims."""
        violations = find_shape_violations(results, audit_dict)
        if violations:
            raise WallError(
                "share shape scan: the coarsened share payload contains "
                f"{', '.join(violations)} — refusing to emit. This means the "
                "coarsening step in share.py did not run, or a field/denominator "
                "was added without being reviewed onto its allowlist; that is a "
                "highest-class bug, report it like one.")

    def n_events(self) -> int:
        return self.audit.n_events

    # ── claim gate ───────────────────────────────────────────────────────
    def admit(self, analyzer) -> bool:
        """True iff every claim the analyzer declares is representable under
        this profile. Person claims need `person_inference` AND an owner
        token; unknown claims are refused outright."""
        for claim in analyzer.claims:
            if claim in PROCESS_CLAIM_TYPES:
                continue
            if claim in PERSON_CLAIM_TYPES:
                if self.profile.grants("person_inference") and self.profile.owner_token:
                    continue
                self.audit.analyzers_refused.append(f"{analyzer.name} (person claim {claim!r})")
                return False
            self.audit.analyzers_refused.append(f"{analyzer.name} (unknown claim {claim!r})")
            return False
        return True
