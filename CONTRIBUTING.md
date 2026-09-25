# Contributing to redax

Thanks for your interest in redax. This document explains how to set up
the project locally, run the test suite, and submit a pull request.

## Reporting issues

Open an issue at
[`sachncs/redax/issues`](https://github.com/sachncs/redax/issues)
using the appropriate template (`bug`, `feature_request`, or `question` via
Discussions if enabled). For security issues, follow
[`SECURITY.md`](./SECURITY.md).

## Development setup

Redax currently targets Python 3.13.

```
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --no-deps -r requirements.lock
python -m pip install -e '.[dev]'
```

## Tests

```
pytest -q
make lint
make typecheck
npm --prefix site run check
npm --prefix site run build
```

## Lint / format

```
ruff check .
ruff format --check .
```

## Pull request flow

1. Fork the repository.
2. Create a topic branch off `master` (use linear history).
3. Make focused commits with clear messages.
4. Ensure tests, lint, type checking, and the site checks all pass.
5. Use the [PR template](./.github/PULL_REQUEST_TEMPLATE.md).
6. Push the branch and open a pull request targeting `master`.

By submitting a pull request, you agree to follow the
[Code of Conduct](./CODE_OF_CONDUCT.md).
