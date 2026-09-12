"""The corpuslens binding for the vendored subject-consent core.

`corpuslens.consent.core` is deliberately blind: it records grants and it
verifies chains, and it does not know who the owner is, what "a run" is, or
what corpuslens should write to a guardian's record. Those are this file's
three jobs, the same split willow-mcp makes between its core and its binding:

1. **Owner == subject needs no grant, and is the default.** Every run without
   `--subject` is the owner's own corpus — the case this tool was built for —
   and the gate is not consulted at all. Naming a subject is the operator
   saying *this corpus is about someone else*; the core has no way to know
   that, so an absent flag must never widen anything. It only ever narrows.

2. **The gate, before anything is read.** `require_grant` runs before the
   adapter opens a single file: a subject whose consent cannot be verified
   has their corpus left unread, not read-then-discarded. It is the core's
   `permitted(store, subject, "process_analysis")`, fail-closed on every path
   the core names (no store, a broken or truncated chain, `pending`,
   `revoked`, no record). This binding adds no path of its own to "allowed".

3. **The disclosure, after.** A guardian's readable record should say that a
   process analysis ran over this subject's corpus. `disclose` appends one row
   to the subject's own hash-chained disclosure log — the adapter and the
   event counts, never the anchor, never a filename, never a number from the
   report — and only after the report cleared the egress scan, so a refused
   run leaves no "analysis ran" row behind.

What this binding pointedly does NOT do, and why:

* It does not wire the core's `person_inference` scope to the Guard's
  `person_inference` capability, though they share a name on purpose. A
  consent grant is *necessary* for a person-shaped claim about someone and is
  not *sufficient*: it says the claim may be about them, not that this tool
  can make it truthfully. `PERSON_CLAIM_TYPES` analyzers stay refused under
  the default profile exactly as before — see `guard.Guard.admit`.

* It does not grant. `grant`/`revoke` are reached only through `corpuslens
  consent ...`, an operator-terminal command, never from `run`; a run that
  could grant itself consent would be the wall with a door in it. The
  README's rule that "there is no CLI flag to grant capabilities" is about
  the Guard's capabilities and still holds; consent is a different object,
  recorded in a different, hash-chained place, by a named grantor.

* It does not judge capacity. Who may grant for a child, a ward, a household
  member is policy the core defers and this binding defers too. The
  grantor's name is recorded on the chain and that is the whole of what the
  tool asserts about it.

The subject identifier is opaque and local. It reaches this module as a
string the operator typed, it is compared and hashed by the core, and it is
never written into a report, an audit sentence, or an error message that
could end up in one — a subject's id in the sentence that says nothing
identifying left the wall would be the same class of leak as the resolved
home directory `AuditRecord.__setattr__` refuses.
"""

from __future__ import annotations

from pathlib import Path

from .consent import core

#: The one scope a `corpuslens run`/`doctor` needs: process and structure may
#: be derived from the subject's data. Not `local_only` (that is about where
#: the data may live, which this tool never changes), not `kb_promotion`
#: (nothing here promotes anything), not `person_inference` (see above).
SCOPE = "process_analysis"

#: What a disclosure row's `action` says. Fixed strings, so a guardian
#: reading the chain sees the same words every time.
ACTION_RUN = "corpuslens run"
ACTION_DOCTOR = "corpuslens doctor"


class SubjectRefused(Exception):
    """Consent for the named subject could not be verified. The message names
    the scope and the reason class, never the subject."""


def require_grant(consent_store: str | Path, subject_id: str) -> None:
    """Fail-closed: raise `SubjectRefused` unless the subject's latest
    `process_analysis` transition is a verified GRANTED."""
    subject_id = (subject_id or "").strip()
    if not subject_id:
        raise SubjectRefused("--subject needs a non-empty identifier")
    store = Path(consent_store).expanduser()
    if not store.is_dir():
        raise SubjectRefused(
            f"consent store directory not found; nothing was read. A subject who is "
            f"not the owner needs a verified '{SCOPE}' grant in a consent store "
            f"(`corpuslens consent grant ...`) before their corpus is opened."
        )
    try:
        core.verify_consent_chain(store)
    except core.ChainTamperError:
        raise SubjectRefused(
            "the consent chain failed verification (edited or truncated); nothing was "
            "read. A record that cannot prove its own integrity does not grant anything."
        )
    if not core.permitted(store, subject_id, SCOPE):
        raise SubjectRefused(
            f"no verified '{SCOPE}' grant for this subject (absent, pending, or revoked); "
            f"nothing was read. Grants are recorded with `corpuslens consent grant`, by a "
            f"named grantor, never by a run."
        )


def disclose(
    consent_store: str | Path,
    subject_id: str,
    action: str,
    *,
    adapter: str,
    n_events: int,
    n_dropped: int,
) -> str:
    """Append one row to the subject's disclosure chain. Counts only: never
    the anchor, never a filename, never a result. Returns the new head hash."""
    detail = f"scope={SCOPE} adapter={adapter} events={int(n_events)} dropped={int(n_dropped)}"
    return core.record_disclosure(Path(consent_store).expanduser(), subject_id, action, detail)


# ── the operator seat: `corpuslens consent ...` ──────────────────────────────


def grant(consent_store: str | Path, subject_id: str, by: str, scope: str = SCOPE) -> str:
    """Record GRANTED for (subject, scope), signed by a named grantor. Returns
    the new head hash. Refuses an unknown scope and an empty grantor (the core's
    own rules); refuses to extend a tampered chain (the core's too)."""
    store = Path(consent_store).expanduser()
    store.mkdir(parents=True, exist_ok=True)
    c = core.grant(store, subject_id.strip(), scope, by.strip())
    core.record_disclosure(
        store, subject_id.strip(), "consent granted", f"scope={scope} by={by.strip()}"
    )
    return c.hash


def revoke(consent_store: str | Path, subject_id: str, by: str, scope: str = SCOPE) -> str:
    """Record REVOKED for (subject, scope). Denies from now on, permanently on
    the record: the grant is not deleted, it is followed."""
    store = Path(consent_store).expanduser()
    c = core.revoke(store, subject_id.strip(), scope, by.strip())
    core.record_disclosure(
        store, subject_id.strip(), "consent revoked", f"scope={scope} by={by.strip()}"
    )
    return c.hash


def status(consent_store: str | Path, subject_id: str) -> dict:
    """What the store currently says about one subject: each scope's verified
    permission, and the subject's disclosure rows (verified, or the chain's
    refusal). Read-only. The subject id is not in the returned dict — the
    caller already has it, and this shape may be printed."""
    store = Path(consent_store).expanduser()
    out: dict = {
        "store_present": store.is_dir(),
        "scopes": {},
        "disclosures": [],
        "disclosure_chain": "verified",
    }
    for scope in core.SCOPES:
        out["scopes"][scope] = bool(store.is_dir() and core.permitted(store, subject_id, scope))
    if store.is_dir():
        try:
            rows = core.read_disclosures(store, subject_id)
            out["disclosures"] = [
                {"action": r.get("action", ""), "detail": r.get("detail", "")} for r in rows
            ]
        except core.ChainTamperError:
            out["disclosure_chain"] = "FAILED verification (edited or truncated)"
    return out
