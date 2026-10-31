---
paths:
  - "**/*.py"
---

# Python rules

- Target **Python 3.13**. Use modern syntax: `X | None` instead of `Optional[X]`, built-in generics (`list[str]`, `dict[str, int]`).
- Type-hint every function signature, including the return type.
- Follow PEP 8 naming: `snake_case` functions and variables, `PascalCase` classes, `UPPER_SNAKE_CASE` module constants.
- Imports: stdlib, third-party, then local (`app.*`), each group separated by a blank line; no wildcard imports.
- Prefer small, pure functions; keep module-level side effects (clients, engines) in one obvious place (`app/database.py`).
- Raise specific exceptions and chain them with `raise ... from e`. Don't catch an exception just to re-raise it unchanged.
- Never use a mutable default argument (`def f(x: list = [])`); use `None` and create the value inside.
- Read configuration from environment variables (loaded from `.env` via `python-dotenv`); never hard-code secrets, ARNs or hosts. The one exception is the loopback test database URL in `tests/conftest.py`, which holds no secret.
- Use f-strings for formatting, but **never** to build SQL with values (see `postgres.md`).
- Docstrings only where the *why* isn't obvious; keep them to one or two lines.
- Once Ruff is set up, code must pass `ruff check .` and `ruff format --check .` (see `ruff.md`); until then, match the existing formatting.
- Pin dependency versions in `requirements.txt` when adding new ones. Dev tools go in the same file for now.
