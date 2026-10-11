# Contributing to logalog

This guide tells you how to set up, check, and release logalog.
The [README](README.md) describes the library behavior.

## Structure

- `src/logalog/`: package source and type marker.
- `tests/`: tests for package behavior.
- `pyproject.toml`: package metadata and tool settings.
- `uv.lock`: exact development dependency versions.
- `justfile`: development commands.
- `mise.toml`: development tool versions.
- `docs/`: the build checklist, the historical plan, and performance records.
- `.github/workflows/`: CI and release workflows.

## Development

Use Python 3.11 through 3.15 and `uv`.
The development tool versions are in `mise.toml`.

```bash
uv sync
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv build --no-sources
```

With `just` available, use `just check`, `just test`, and `just build`.
`just check` runs Ruff, Ty, Complexipy, Deptry, Vulture, Bandit, and pip-audit.
Use `just lint` for local static checks. `just security` needs network access
for its audit of locked runtime dependencies. Development tools are not runtime dependencies.

Complexipy compares functions against `complexipy-snapshot.json` and a threshold of 15.
The baseline records existing complexity in `command` and `_deliver`.
Review those functions before replacing the baseline with `uv run complexipy --snapshot-create`.
Do not update it only to make a check pass. Vulture checks source and tests at 90% confidence.
Bandit reports findings with at least medium severity and medium confidence.

Pytest Randomly changes test order and reports its seed. Use `just test-random 42`
to repeat a seed. Hypothesis checks module-name encoding across Unicode inputs.
Pytest Asyncio runs coroutine tests in strict mode with function-scoped event loops.

Pytest Sugar supplies interactive progress. Use `just test-spec` for specification
output. That command disables Sugar to prevent conflicting output formats.

Use `just matrix` to run the Python 3.11–3.15 tests through Nox and uv.
The five Python sessions run concurrently. Tests within each session remain sequential.
Each session keeps coverage data, the pytest cache, and Hypothesis data in its own
`.nox/tests-3-XX/test-artifacts/` directory and independently enforces 100% coverage.
Nox currently labels parallel execution experimental.

Use `uv run nox --parallel 1` for sequential sessions.
`just test-matrix` remains an alias. Nox reuses isolated environments, installs
from the frozen lockfile, and fails if a required interpreter is missing.
Use `uv run nox -s tests-3.12 -- --randomly-seed=42` to select a session and pass pytest arguments.
Tests cover output, caller information, exceptions, explicit input checks, threads, import safety, and application handler isolation.

Full test runs fail below 100% line and branch coverage of `logalog`.
Coverage includes subprocess execution.
Use `just coverage` to write an HTML report to `htmlcov/index.html`.

Use `just test-images` for the OpenImageIO visual regression checks.
The comparison runs in [`tests/visual/compare.py`](tests/visual/compare.py), a uv script with its own lockfile.
The checks need `uv` on `PATH`.
They cover levels, wrapping, indentation, tables, styles, code, and commands
at multiple widths. Two representative cases also check queued delivery.
See [image test guidance](tests/visual/README.md) for fonts and reference updates.

For focused tests, use `uv run pytest --no-cov <test-path>`.
Run the full suite before you finish a change. Do not add exclusions to reach the coverage target.

Each accepted call creates one Loguru event. Native file sinks retain its original
message, exception, timestamp, and user fields. The console adapter changes only
a local copy for presentation. Prepared console data stays outside JSON record fields.

The backend adapter uses private Loguru constructors to create an independent logger.
It also reuses Loguru's private `StandardSink` adapter for Rich output.
Copying the shared logger can fail when an application has existing file handlers.
The dependency range limits Loguru to `>=0.7.3,<0.8`.
Test the adapter before changing that range.

## Plan

Use the [build checklist](docs/checklist.md) for the next work chunks.
Keep the [development plan](docs/plan.md) as reference material.
Add one working layer at a time.

## Release

The project uses trusted publishing from GitHub Actions. No API token is necessary.

Do these steps one time before the first release:

1. On PyPI and on TestPyPI, add a pending trusted publisher for the `logalog` project.
   Use the owner `taranjlu`, the repository `logalog`, the workflow `release.yml`,
   and the environments `pypi` and `testpypi`.
2. On GitHub, create the environments `pypi` and `testpypi`.
   Add yourself as a required reviewer for `pypi`.

Do these steps for each release:

1. Set `version` in `pyproject.toml`. Run `uv lock`.
2. Move the `Unreleased` entries in `CHANGELOG.md` to a new version heading.
3. Run `just check`, `just matrix`, and `just build`.
4. Commit the change and push `master`.
5. Run the release workflow by hand with the `testpypi` target. Install the package from TestPyPI and test it.
6. Create a signed tag, for example `git tag -s v1.0.0 -m "logalog 1.0.0"`, and push it.
   The tag starts the release workflow. The workflow checks that the tag agrees with the package version.
7. Approve the `pypi` deployment on GitHub.

The publish step adds PEP 740 attestations to each file.
PyPI keeps each version permanently. If a release has an error, release a new version.
