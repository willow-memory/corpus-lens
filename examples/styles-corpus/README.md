# The style corpus — a falsifier for the authorship classifier

Six invented operators, none of them this project's author, written to **break**
the human/agent classifier rather than to confirm it.

## Why it exists

The thresholds in `corpuslens/authorship.py` were derived from one operator's
own corpus, where human turns ran **3–27 words** and dispatched-agent prompts
ran **453–686**. Perfect separation. But that operator prompts in an unusually
terse and precise way, and most people do not. The separation may be a fact
about one person rather than about people.

## What it showed, immediately

The measured evidence leaves a **426-word gap with no data in it**, and any
threshold inside that gap fits the evidence equally well. Where the line falls
decides who gets called a machine:

| threshold | humans misread as agents | machines missed |
|---|---|---|
| 30 | rambler, spec_writer, second_language | terse_dispatcher |
| 50 | rambler, spec_writer | terse_dispatcher |
| 75 and above | — | terse_dispatcher |

A threshold just above the observed human maximum misreads **three of five**
plausible humans as machines. Every threshold that protects those humans misses
the terse machine, which is a real shape: plenty of automation dispatches in
five-word commands.

**There is no threshold on word count alone that gets all six right.**

## What this corpus can and cannot tell you

It can **falsify**. If the classifier calls the rambler a machine, that is a
real defect, because people who write like that exist.

It cannot **validate**. Everyone here was imagined by the same author whose
blind spots the test is meant to expose, so passing says nothing about the true
error rate on real people. For that, run `corpuslens label` on a real corpus and
`corpuslens score` to get a measured number.

`truth.json` records the true author per turn — the one thing a synthetic
corpus has that a real one does not.

## Rebuilding

```bash
python3 examples/styles-corpus/build.py
```
