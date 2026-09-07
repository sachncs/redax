# Conventions for agents working on Redax

## Code style

- Python 3.11+. `from __future__ import annotations` not needed.
- No semi-private naming (`_underscore` methods). Everything called from elsewhere is public.
- Prefer concrete classes over Protocol unless multiple implementations exist now or are genuinely planned.
- One module = one responsibility. If a file mixes concerns, split it.
- Public API of a module is what other modules actually import. Everything else is implementation detail; do not export it.
- No module-level globals for stateful resources (model, redis, audit). Wire them in `app/main.py` lifespan and pass via parameters or `app.state`.

## Tests

- Run before committing: `make test lint typecheck`.
- Unit tests live in `tests/unit/`, integration in `tests/integration/`.
- For new public functions, add a test in the matching file. Use `hypothesis` for properties over random inputs.
- For known input/output pairs, use `pytest-approvaltests` snapshots.

## Commits

- Atomic: one focused change per commit.
- Reference the milestone + item number from the plan in the commit subject (e.g. `M1 #22: add Detector Protocol`).
- Author: `sachin <sachncs@gmail.com>`.

## What to avoid

- Thin wrappers around a single concrete class.
- Factory functions / registries when `import` works.
- Plugin architectures when there's exactly one plugin.
- Private "helper" methods on public classes — make them module-level functions instead.
- "Just in case" abstraction. Add polymorphism when a second implementation actually appears.
- Global mutable state. Configuration belongs in `app/config.py:Settings`; resources belong on `app.state`.

## Verification commands

```bash
make install
make dev       # server on :8000
make test
make lint
make typecheck
```
