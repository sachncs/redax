# Milestone plan

This file documents the `M<n> #<id>` commit-tag convention referenced by the
project, in particular by the M11 audit batch (107 issues, see
`gh issue list --label audit/M11`).

A milestone tag is two parts:

- `M<n>` — the milestone number (M1, M2, ..., M11). M11 is the current
  audit pass and corresponds to the issues with the `audit/M11` GitHub
  label.
- `#<id>` — the GitHub issue number (e.g. `#108`). This pinpoints the
  finding inside the milestone.

When a commit references `M11 #225: short summary`, it means:

> The M11 audit identified issue #225 (a "CHANGELOG 0.1.0+ lacks an item
> describing the audit pass itself" finding); this commit addresses it.

A future reader can look up the issue body for the full context.

## How to read a tag

```
M11 #225: CHANGELOG 0.1.0+ lacks an item describing the audit pass itself
^^^^ ^^^^
   |   +-- GitHub issue number in the sachncs/redax repo
   +------ Milestone id (audit/M11 label)
```

If you don't have access to GitHub, the local issue JSON dump at
`/tmp/opencode/issues/sachncs_redax.json` carries the same data.
