# Contributing to corpuslens

Thanks for looking. corpuslens is a small, honest tool with a few load-bearing
rules. Contributions are welcome as long as they hold the rules — most of what
follows is about *what not to break*, because that is where this project's value
lives.

## The one rule: never overclaim

The docs, the docstrings, and the run's audit sentence must never promise more
than the code delivers — including claims about what the tool itself protects.
If you change what the code does, change the claim in the same PR. Two concrete
forms this takes:

- **The wall's claims must match the wall's code.** The README and `guard.py`
  say exactly what does and does not leave the wall (the absolute date, weekday
  label, timezone, and filenames are kept out; weekly cadence and a loose
  within-day time-of-day bound are *disclosed as not hidden*). If you add a field
  to `Event` or change the timing channel, re-audit those claims and the audit
  sentence in `guard.py`.
- **Classifiers undercount rather than overclaim.** The regex classifiers
  (`CODE_REF`, `AUTHORED`, `DELIB`, `CLARIFY`) feed headline percentages. When
  they are wrong, they must be wrong in the *under*-counting direction — a false
  negative on real code is acceptable; a false positive on ordinary prose that
  inflates "you write code" is not. Add prose fixtures for any classifier change.

## The wall discipline (for new adapters and analyzers)

- **A new adapter** must never put an absolute calendar date, timezone, or raw
  source locator on an `Event`. Dates become relative `day_offset`s from the
  corpus start; the calendar anchor and the real locator (a `filename:line`, or
  a `table:row`) go into the `Quarantine` (reachable only through the `Guard`);
  session/thread ids are opaque hashes. Count every skipped record toward
  `dropped` — nothing silently discarded — and never let one malformed record or
  unreadable source crash the run. A DB-sourced adapter has the same duty as a
  file one: a connection string or db path can embed a username or home dir just
  as a filename embeds dates, so it must never reach an `Event` unhashed — route
  every row through `ingest/_rows.py::assemble`, which is the file adapters'
  proven wall logic factored out so a database backend cannot re-derive (and
  quietly weaken) it. New adapters declare their source kind via
  `register(name, source="file"|"dsn"|"dir")` so the CLI validates the argument
  correctly instead of assuming a directory.
- **A new analyzer** must declare a `claim` type on the process-only allowlist
  in `model.py` (a person-shaped claim like `life_partition` stays behind the
  capability gate and out of the default registry) and a **named denominator**
  that matches its actual filter. Analyzers receive only the `Event` list —
  relative time and process features, never content.

If you find a way for a default-profile analyzer to recover the absolute anchor
via the supported path, that is a security issue, not a feature request — see
[SECURITY.md](SECURITY.md).

## Reference numbers are verified from raw

The reference points in the analyzers (the measured N=1, the WildChat/OASST
aggregates) were derived from raw sources and re-verified. If you change a
reference number, say where it came from and how it was checked — never adjust a
reference to make a result look better.

## Running the tests

```bash
python -m unittest discover -s tests -v
python -W error::ResourceWarning -m unittest discover -s tests   # no leaked handles
```

Every fixed bug gets a regression test; the wall tests (`tests/test_wall.py`)
are the acceptance tests for the centerpiece — including one that *documents*
what the wall does NOT hide, so nobody silently re-introduces an overclaim. CI
runs the suite on Python 3.10–3.14 plus a packaging smoke test.

## The Idea-Id commit-trailer convention

A commit that lands an idea recorded in [docs/ideas.md](docs/ideas.md) carries
an `Idea-Id: willow-ideas-<num>` git trailer (add `Idea-Status: partial` when a
commit only partly lands it). The prefix is the fleet's, not this repo's — at
willow-reconciler 0.6.0 `reconciler/ids.py` derives the id from the item's
number alone. It is the durable join key willow-reconciler reads; a wrong id is
worse than no id, so never type one by hand:

    reconciler id --repo ./ --doc docs/ideas.md --grep "words from the item"
    reconciler install-hook --repo ./       # derives it from a branch named idea-NN

The reconciler is not a dependency of this repo (stdlib-only, tests included);
install it in a throwaway venv, `pip install "willow-reconciler>=0.6.0"`, to
run those. Write the repo as `./`, not `.`: at 0.6.0 a `--repo` with no slash
in it is read as a bare fleet name, not a path. `.github/workflows/trailers.yml` runs `reconciler verify` on every
PR and fails on a trailer that names an item the doc does not contain. The
long-form reasoning behind each item stays in [IDEAS.md](IDEAS.md); the
numbers in docs/ideas.md are permanent and are never reused.

## Releasing

Releases are cut by release-please, on the fleet's standard shape (ported from
forge-play/Forge — keep it identical unless this repo has a reason of its own;
divergent copies of a release pipeline are how one repo silently stops
publishing). The distribution on PyPI is **`willow-corpus-lens`**; the import
package and the console script are both **`corpuslens`**.

### The flow

```
merge to main  →  release-please opens "chore(main): release X.Y.Z"
               →  auto-merge arms, waits for the `test` gate
               →  merging it cuts the tag vX.Y.Z
               →  the tag fires release.yml  →  PyPI
```

Nothing publishes from a branch, and nothing publishes by hand. A release PR
sits open accumulating every merge to `main` until someone (or auto-merge)
merges it, so a release ships when CI is green rather than when someone
remembers.

### What a contributor is asked for

- **Conventional commit messages**, because they are what picks the version and
  writes the changelog. `feat:` cuts a minor, `fix:` a patch, `feat!:` or a
  `BREAKING CHANGE:` footer goes to the next major. `docs:`, `test:`, `ci:` and
  `chore:` are hidden — they ride along with the next real release rather than
  shipping a version containing nothing a user installs. Every *un*-hidden type
  cuts a release on its own, not just `feat` and `fix`.
- **A commit that changes what leaves the wall is never `chore:` or
  `refactor:`.** `guard.py`, the audit sentence, an adapter's quarantine
  handling — those are `feat:`, `fix:` or `security:`, so the change gets a
  version number someone can point at. A release is a wall event: the published
  artifact is what strangers run on their own logs.

### The version lives in the git tag, and nowhere else

`pyproject.toml` declares `dynamic = ["version"]` and hatch-vcs derives it from
the tag; `corpuslens/__init__.py` reads it back from installed distribution
metadata. **Do not add a version literal to either.** A literal is a second copy
that drifts: before this was fixed, `pyproject.toml` said `0.1.0` with nothing
tagged or published, and `__init__.py` said `0.1.0` while the build produced
`0.1.dev41`. A test asserts both stay derived, and asserts the distribution name
agrees across all four places that spell it (pyproject, `__init__`,
release-please's `package-name`, and the artifact regex in `release.yml`, which
sees the PEP 625 underscored form) — three of the four agreeing is the failure
mode, and it surfaces at upload where the error is useless.

Guards that run before anything reaches PyPI, in order: the tag must match the
built version; `twine check` must pass; and the built **wheel** is installed
into a clean virtualenv where the console script, the adapter listing, the audit
line and the JSON output are all re-checked. The artifact strangers install is
the one that gets tested, not the checkout it came from.

### The first release is not what you would guess

**With no prior release, release-please's first release is `1.0.0` whatever the
manifest says.** A `0.0.0` manifest does not make it `0.1.0`. This repository
learned that by publishing a `1.0.0` it did not mean — on a spine, for a project
whose one rule is never to overclaim, where the version number is itself a
compatibility promise. The recovery cost a deleted PyPI project, because **a
PyPI version can never be reused or replaced.**

To choose a first version deliberately, either set `initial-version` in
`release-please-config.json` *before* the first release, or put a
`Release-As: <version>` footer in a commit message — release-please's own
override, which keeps the release cut by the pipeline rather than by a
hand-pushed tag. Every release *after* the first bumps from the manifest
normally.

### Known gap: duplicates in a first release's changelog

This repo merges with merge commits rather than squashing, and GitHub writes the
PR title into the merge commit body — so release-please parses one change twice,
once from the real commit and once from the merge commit carrying its title.
`tools/changelog_dedup.py` runs in the release workflow to rebuild the section
from the commits and drop merge commits, and it works.

It **cannot** fix a *first* release. Its section matcher expects the
`## [x.y.z](…/compare/…)` heading release-please writes for every release after
the first, and a first release has no previous tag to compare against. If you
bootstrap another repo from this shape, expect its first changelog section to
carry duplicates and fix them by hand. Per that file's own docstring, the tool
is fixed in forge-play first and then re-synced here — do not let the copies
diverge.

### Setup that lives outside this repository

None of it is optional, and each item fails quietly or confusingly if missed.
`.github/workflows/release-please.yml` carries the same list in its header:

1. The **willow-ci GitHub App** installed on the org, with `WILLOW_CI_APP_ID`
   and `WILLOW_CI_PRIVATE_KEY` reachable. The workflow refuses to fall back to
   `GITHUB_TOKEN` on purpose: GitHub suppresses workflow runs for events
   generated with that token, so a tag cut with it starts no release workflow
   and nothing ever reaches PyPI — everything reads as fine.
2. **Allow auto-merge** enabled in the repository settings.
3. Branch protection on `main` requiring the aggregate **`test`** check. With no
   required check there is nothing for auto-merge to wait on, and GitHub
   declines to arm it at all.
4. A **`pypi` environment** on the repository.
5. A PyPI **Trusted Publishing** publisher for project `willow-corpus-lens`,
   bound to this repository, workflow `release.yml`, environment `pypi`. All
   three must match exactly, and the project name must match the distribution
   name — Trusted Publishing binds to the *name*, and a mismatch is rejected at
   upload. No API token is stored anywhere; uploads carry PEP 740 provenance.

### If a release does not publish

`release.yml` also takes a `workflow_dispatch` with a tag name: the recovery
path for a tag that exists but never published. Check, in this order, whether
the release PR was created, whether auto-merge armed, whether the tag was cut,
and whether the publish job ran — the failure is almost always one of the five
setup items above, and the logs name it.

## Scope

corpuslens is **owner == subject** by default: a tool you run on your own logs
to study yourself. Pointing it at another person is a different consent object.
That object now exists — `corpuslens/consent/` (vendored from willow-mcp,
hash-pinned; never edit it in place, re-vendor) and the binding in
`corpuslens/subject_consent.py` — and it gates exactly one thing: whether a
named non-owner subject's corpus may be *read for process* at all. It does not
open the door to person-shaped claims; `person_inference` stays unwired from
the Guard on purpose, and the ethics half (who may consent for whom) is the
human's, not the tool's. PRs that add person-targeting analysis on the strength
of a grant will be declined on those grounds, not on quality.

## How we work here

Plainly and honestly. Disagreement is welcome; a PR that makes the tool claim
*less* is usually more valuable than one that makes it claim more. Be kind, be
specific, and when you are not sure, say so.
