# Python Dependency Lock Design

**Date:** 2026-08-17
**Iteration:** 150
**Status:** Approved for autonomous implementation

## Context

The project declares lower-bounded runtime and development dependencies in
`pyproject.toml`, while CI resolves them from the package index on every run.
The frontend already uses `package-lock.json` and `npm ci`; Python has no
equivalent exact transitive lock, despite the development guide classifying
that gap as P1 and requiring verified dependency locks before automatic
downloads.

## Options Considered

1. **One universal, hash-checked requirements lock.** Resolve the default and
   `dev` dependency groups for the full supported Python 3.10+ range, pin every
   transitive dependency, and require hashes during CI installation. This is
   selected because it gives one auditable input to local and Linux CI.
2. **Pin only direct dependencies in `pyproject.toml`.** This is smaller but
   leaves transitive packages free to drift, so it does not meet the stated
   reproducibility goal.
3. **Maintain one lock per OS and Python minor.** This is maximally specific
   but creates a matrix the project does not currently test or automate. It is
   deferred until platform-specific dependencies require it.

## Decision

Create `requirements.lock` from `pyproject.toml` with exactly
`uv==0.12.5`, `--universal`, `--python-version 3.10`, `--extra dev`,
`--no-sources`, and `--generate-hashes`. A custom compile-command header
records those exact inputs because the generator executable itself is outside
the lock. The file must contain no package index URL, trusted-host
directive, editable requirement, VCS reference, local path, or unverified
archive URL. It locks third-party runtime and test/build tooling only; the
repository package remains editable and is installed separately with
`--no-deps --no-build-isolation`.

CI installs the lock with:

```text
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
```

The project declares `setuptools.build_meta` explicitly and includes the same
setuptools lower bound in `dev`, so the lock pins its build backend. Python
3.10 also declares the `tomli` backport used by repository TOML guards, while
3.11+ uses the standard-library `tomllib`. Disabling build isolation for the
editable install prevents pip from resolving a second, unhashed build
environment. The lint job consumes the same lock so Ruff no longer floats
independently.
The lock intentionally excludes Python, pip, and the editable project itself;
CI pins Python 3.11 through `actions/setup-python` and pip remains bootstrap
infrastructure.

## Drift Guard

An offline test reads `pyproject.toml` and `requirements.lock`, using `tomllib`
on Python 3.11+ and the declared `tomli` backport on Python 3.10. It requires:

- every default and `dev` direct dependency to appear as one exact `==` pin;
- every locked requirement block to contain at least one SHA-256 hash;
- each normalized package name and environment-marker pair to be unique;
- repeated package names to carry distinct non-empty universal markers;
- no index, trusted host, editable, VCS, local path, or URL requirement;
- the fixed universal generation command to remain in the lock header;
- CI to use `--require-hashes` and
  `--no-deps --no-build-isolation -e .`, with no floating
  `pip install ruff` or `pip install -e ".[dev]"` command.

This guard checks lock shape and input coverage without network access. A
separate isolated-venv verification performs a real hash-enforced install.

## Compatibility And Scope

- Keep the existing lower bounds in `pyproject.toml`; they remain package
  metadata for downstream consumers while the lock controls repository CI.
- Do not change runtime code, APIs, Worker policy, or supported Python floor.
- Do not introduce an application package manager at runtime.
- Do not stage, commit, reset, clean, or revert mixed-worktree changes.
- Regeneration is an explicit maintainer action and must be followed by the
  drift guard, isolated install, and project verification.

## Verification

1. Add the lock guard and observe it fail because `requirements.lock` is
   absent.
2. Generate the universal hash lock with the exact pinned command and require
   the focused guard to pass.
3. Update CI and docs, then require CI guard tests to pass.
4. Install the lock into a fresh temporary virtual environment with
   `--require-hashes`, install the project with
   `--no-deps --no-build-isolation -e .`, and import
   all direct runtime dependencies.
5. Run aggregate/discovery suites, compileall, Ruff, frontend gates, local
   integration, diff review, and Iteration 150 ledger guards.

## Exit Criteria

- `requirements.lock` universally pins the complete runtime and `dev`
  dependency graph with hashes and explicit forks where one version cannot
  support the full Python range.
- Static tests detect missing direct dependencies, non-exact entries, missing
  hashes, unsafe sources, generator drift, and CI bypasses.
- A clean temporary environment installs successfully from the lock with hash
  enforcement.
- Existing project behavior and all verification gates remain green.
