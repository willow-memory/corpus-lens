"""corpuslens.consent — the fleet's shared subject-consent core, vendored.

Read ``core.py``'s header for provenance and for exactly what corpuslens wires
this to. The binding that consults it lives in ``corpuslens/subject_consent.py``;
this package is the primitive only and imports nothing from corpuslens.
"""
from __future__ import annotations

from .core import (
    RELATIONS,
    SCOPES,
    Backend,
    ChainTamperError,
    Consent,
    DeidentificationError,
    FileBackend,
    Subject,
    SubjectConsentError,
    deidentify,
    grant,
    permitted,
    read_disclosures,
    record_disclosure,
    revoke,
    verify_consent_chain,
)

__all__ = [
    "SCOPES",
    "RELATIONS",
    "Subject",
    "Consent",
    "Backend",
    "FileBackend",
    "SubjectConsentError",
    "DeidentificationError",
    "ChainTamperError",
    "grant",
    "revoke",
    "permitted",
    "verify_consent_chain",
    "deidentify",
    "record_disclosure",
    "read_disclosures",
]
