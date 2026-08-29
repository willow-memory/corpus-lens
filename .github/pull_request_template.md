<!-- Thanks for contributing. corpuslens has a few load-bearing rules; this
checklist is how we keep them. See CONTRIBUTING.md. -->

## What this changes


## Checklist

- [ ] `python -m unittest discover -s tests` passes
- [ ] `python -W error::ResourceWarning -m unittest discover -s tests` passes (no leaked file handles)
- [ ] **No overclaim added** — the README, docstrings, and the audit sentence still match what the code actually does
- [ ] If a classifier changed: it errs toward **under**-counting, and prose/real-code fixtures were added
- [ ] If an analyzer was added: it declares a process-allowlist `claim` type and a **named denominator** matching its filter
- [ ] If an adapter was added: no absolute date / timezone / raw filename reaches an `Event`; every skipped line is counted; a malformed line or unreadable file cannot crash the run
- [ ] Reference numbers (if changed) are sourced and verified from raw, not tuned to a result

## Notes

<!-- Anything a reviewer should know: a disclosed limit you touched, a tradeoff,
an open question. When you're not sure, say so. -->
