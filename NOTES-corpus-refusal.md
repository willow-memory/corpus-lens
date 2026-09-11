# Doc changes needed for the corpus-refusal work

Branch: `claude/expand-corpus-refusal`. Per instructions I did not touch
`README.md` or `IDEAS.md` directly (parallel agents). Below is exactly what
each needs, old text quoted first, new text after.

## README.md

One bullet in the "named and deliberately unbuilt" list is now stale — it
listed this feature as not built yet:

**Old:**

```
- A local labelling mode, a share-safe report, and a corpus-type refusal are
  the next things in IDEAS.md's near list; none exists yet, and the report says
  "trust direction plus your own spot-check" until the first one does.
```

**New:**

```
- A local labelling mode and a share-safe report are still the next things in
  IDEAS.md's near list. The corpus-type refusal has shipped: `composition_mix`
  and `clarification_pull` return `{"error": ...}` once a corpus has more than
  `SMALL_N` operator/machine turns and their classifiers matched none of
  them, naming both readings (not a coding corpus vs. a corpus these regexes
  cannot read) without picking one. The report still says "trust direction
  plus your own spot-check" for everything the classifiers DO compute.
```

I'd also suggest a one-sentence addition to "Honesty about the numbers"
(unedited by me — same reason), right after the existing text:

**Old:**

```
## Honesty about the numbers

The classifiers are regex heuristics: trust direction plus your own
spot-check, never raw percentages. The reference N=1 was verified by
re-derivation from raw and corrected five times in one session — the
reference table inherits those corrections, not the first drafts.
```

**New:**

```
## Honesty about the numbers

The classifiers are regex heuristics: trust direction plus your own
spot-check, never raw percentages. They are also English-and-Python shaped —
`CODE_REF` and `AUTHORED` recognize a short list of file extensions and a
handful of languages' block syntax, `DELIB` and `CLARIFY` are lists of English
phrases — so a real coding (or deliberating) corpus in a shape they don't
parse looks identical to one with none of that in it. Past a sample size
where that would matter, `composition_mix` and `clarification_pull` refuse
rather than report the resulting zero as a finding. The reference N=1 was
verified by re-derivation from raw and corrected five times in one session —
the reference table inherits those corrections, not the first drafts.
```

## IDEAS.md

The spec entry under Near — `### Refuse a corpus the classifiers cannot
read` — describes the feature as not-yet-built. Now that it exists, the
entry should get the same "dated addendum" treatment already used elsewhere
in this file (see the `*2026-09-11:*` note under "Corpora that are not
code"), rather than being deleted — IDEAS.md's own convention is to record
what changed and when, not to silently remove entries once done.

**Append, directly after the existing paragraph that ends "...The analyzers
that would _replace_ these for another domain stay in Stretch."**:

```
*Implemented* (this branch, `claude/expand-corpus-refusal`): `composition_mix`
refuses when operator turns exceed `SMALL_N` (moved from `render.py` to
`analyze/__init__.py`, since an analyzer now reasons about it directly, not
only the renderer) and both `CODE_REF` and `AUTHORED` matched zero of them;
`clarification_pull` refuses the same way when machine turns exceed `SMALL_N`
and `CLARIFY` matched none. Both error messages name the two readings and
pick neither. `delib_pct` is dropped from `composition_mix`'s refusal
entirely, even though `DELIB` is independent and may have fired — see that
function's docstring for why (the reference comparison it would need is
itself ambiguous once the corpus's code-status is unknown). A
deliberation-only analyzer, decoupled from code composition's population
choice, stays a candidate for this file rather than a quiet carve-out in the
refusal path.
```

## examples/EXAMPLE.md

No change needed, and I confirmed this rather than assumed it:
`examples/sample-corpus` has n=10 operator turns and n=10 machine turns for
`composition_mix`/`clarification_pull`, both well under `SMALL_N` (30), so
neither analyzer refuses on it. Re-ran
`python3 -m corpuslens run examples/sample-corpus --adapter claude-code` after
the change — output is byte-for-byte the same as what EXAMPLE.md documents.
