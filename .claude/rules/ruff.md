---
paths:
  - "**/*.py"
  - "pyproject.toml"
---

# Ruff rules

Status: planned. These apply once `chore/ruff` lands.

- Configure Ruff only in `pyproject.toml`, which holds tool config and no `[project]` table.
- Line length is 100. Target is Python 3.13.
- Selected rules: `E, W, F, I, UP, B, N, SIM, RUF, ANN`. `E501` is ignored because the formatter owns line length.
- Exclude `alembic/versions/` from both lint and format, so Ruff never rewrites an applied migration. `alembic/env.py` stays included.
- Keep `force-exclude = true`. Without it, a path passed explicitly (by an editor or hook) bypasses the exclusion.
- Keep `alembic` in `known-third-party`. The repo's `alembic/` folder otherwise makes Ruff sort the package as first-party.
- Run `ruff check .` and `ruff format --check .` before committing. Use `--fix` and `ruff format .` to apply changes.
- Fix the code rather than adding `# noqa`. When a `noqa` is needed, name the rule and say why (`# noqa: F401  registers the tables on Base.metadata`).
- Add a rule family only when it would catch a real problem in this code, not to widen coverage.
- Keep formatting changes in their own commit, separate from behaviour changes.
- Run Ruff from the venv. Conda's older `ruff` otherwise shadows the pinned version.
