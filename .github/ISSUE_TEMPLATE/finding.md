---
name: Finding report
description: Report a finding from a code audit, security review, or deep-review pass.
title: "[<severity>] <one-line summary>"
labels: ["audit/M11"]
assignees: []
---

## Summary

One paragraph. State the problem in the operator's or contributor's voice.

## Location

- **File:** `path/to/file.py`
- **Lines:** `NN–NN`
- **Severity:** `blocker` / `major` / `minor` / `nit`

## Current state

Quote the offending code or document the exact mismatch between docs and
implementation. Link to other files where the same pattern recurs.

## Why it matters

One short paragraph explaining the concrete impact: a behavior the user
sees, a guarantee we can't keep, an attack surface, an ergonomics cliff,
or a maintainability tax.

## Proposed approach

Concrete, atomic steps. Prefer the smallest change that closes the gap
without introducing new abstractions. Reference related findings so the
fix can be batched into one commit if desired.

## Acceptance criteria

- [ ] The proposed change is implemented and committed with a
      milestone-prefixed subject (`M<n> #<id>: ...`).
- [ ] `make verify` is green.
- [ ] Any new public symbol has a docstring + matching test.

## References

- File:line of every related call site.
- Doc page or CHANGELOG entry affected.
- Any external issue, RFC, or paper that motivated the finding.
