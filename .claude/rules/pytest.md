---
paths:
  - "tests/**/*.py"
  - "docker-compose.yml"
  - "pyproject.toml"
---

# pytest rules

Status: planned. These apply once `test/pytest-setup` lands. Rationale is in `DESIGN.md` §10.

## Database

- Tests run against `postgres:17` from `docker-compose.yml`, on `127.0.0.1:5433`, in the `ai_triage_test` database, with `POSTGRES_HOST_AUTH_METHOD=trust`. Bind the port to loopback only; `trust` is safe only because of that.
- `tests/conftest.py` hard-sets `os.environ["DATABASE_URL"]` before any `app` import. Never use `setdefault`: a stray value in the shell or `.env` must not redirect tests.
- Build the schema with `alembic upgrade head` in a session-scoped fixture. Never use `Base.metadata.create_all()`, which would pass even with a missing migration.

## Writing tests

- Test through HTTP with `TestClient`, using the real database and no mocks. Add repository or service tests only for logic HTTP can't reach.
- Each test uses a session on an open transaction, supplied through `app.dependency_overrides[get_session]` and rolled back afterwards. Don't write teardown for rolled-back data.
- Name files `test_<resource>_api.py` and tests `test_<behaviour>`. Assert on status codes and response bodies.
- A test that commits for real skips the override and cleans up after itself. Keep these rare.
- Every migration must pass the downgrade and upgrade round-trip test.

## Aurora

- Mark tests that need AWS with `@pytest.mark.aurora`. `addopts = "-m 'not aurora'"` excludes them by default; run them deliberately with `pytest -m aurora`.
- An Aurora test builds its own engine with `create_iam_engine()`, because the forced `DATABASE_URL` means the module-level `engine` is local.
