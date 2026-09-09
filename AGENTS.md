# Agent guidance

Read `README.md` before you change this project.
Read `docs/plan.md` before you change the planned design.
Repository code, tests, and accepted decisions define the project behavior.

## Scope

This repository contains a Python library skeleton.
Do not treat the proposed logging API as implemented.
Do not copy device code or release machinery from another project.
Add dependencies when project code needs them.
Do not publish packages or create a remote without approval.

## Code

Use the `src/` layout and typed Python interfaces.
Use NumPy-style docstrings.
Write parameter defaults as `default=<value>` instead of `optional`.
Keep logging output separate from application standard output.
Do not change an application's logging handlers without an explicit ownership policy.
Do not log secrets or execute subprocess commands in a display helper.

## Verification

Run these commands before you finish a code change:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```

For package changes, build and test the wheel outside the checkout.
Add tests for observable behavior and failure cases.
Do not add tests only to increase a coverage number.

## Writing

Use ASD-STE100 Simplified Technical English as the writing target.
Use short sentences, active voice, and consistent terms.
Preserve exact code, API names, and technical meaning.
Do not claim formal compliance without the required review.

## Commits

Use an imperative subject with an initial capital and no final period.
Aim for 50 characters or fewer. Do not exceed 72 characters.
Keep each commit focused on one change.
