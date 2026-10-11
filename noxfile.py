"""Run the supported Python test matrix with Nox and uv."""

from __future__ import annotations

from pathlib import Path

import nox

PYTHON_VERSIONS = ["3.11", "3.12", "3.13", "3.14", "3.15"]

nox.needs_version = ">=2026.8.17,<2027"
nox.options.default_venv_backend = "uv"
nox.options.error_on_missing_interpreters = True
nox.options.reuse_venv = "yes"
nox.options.parallel = len(PYTHON_VERSIONS)


@nox.session(python=PYTHON_VERSIONS, allow_parallel=True)
def tests(session: nox.Session) -> None:
    """Run the test suite on one supported Python version."""
    environment = {"UV_PROJECT_ENVIRONMENT": str(session.virtualenv.location)}
    session.run_install(
        "uv",
        "sync",
        "--frozen",
        f"--python={session.virtualenv.location}",
        env=environment,
    )
    artifacts = Path(session.virtualenv.location).resolve() / "test-artifacts"
    artifacts.mkdir(exist_ok=True)
    session.run(
        "pytest",
        "-q",
        "-o",
        f"cache_dir={artifacts / 'pytest-cache'}",
        *session.posargs,
        env={
            "COVERAGE_FILE": str(artifacts / ".coverage"),
            "HYPOTHESIS_STORAGE_DIRECTORY": str(artifacts / "hypothesis"),
        },
    )
