---
paths:
  - "tests/**/*.py"
  - "docker-compose.yml"
  - "pyproject.toml"
---

# pytest rules

Rationale is in `DESIGN.md` §10.

## Database

- Tests run against `postgres:17` from `docker-compose.yml`, on `127.0.0.1:5433`, in the `ai_triage_test` database, with `POSTGRES_HOST_AUTH_METHOD=trust`. Bind the port to loopback only; `trust` is safe only because of that.
- `tests/conftest.py` hard-sets `os.environ["DATABASE_URL"]` before any `app` import, so Ruff's `E402` is ignored for that file only. Never use `setdefault`: a stray value in the shell or `.env` must not redirect tests.
- Build the schema with `alembic upgrade head` in a session-scoped fixture. Never use `Base.metadata.create_all()`, which would pass even with a missing migration.

## SQS

- Tests use ElasticMQ from `docker-compose.yml` on `127.0.0.1:9324`. `tests/conftest.py` hard-sets `SQS_ENDPOINT_URL`, `TRIAGE_QUEUE_URL` and `AWS_REGION` next to `DATABASE_URL`, so no test can reach AWS.
- The queue isn't rolled back with the database. Tests that send or receive use an autouse fixture that purges the queue before and after each test.
- A test that commits for real must also delete the outbox events it wrote, or the relay tests will publish them.

## Writing tests

- Test through HTTP with `TestClient`, using the real database and no mocks. Add repository or service tests only for logic HTTP can't reach.
- To set up a state the API can't reach, such as a `FAILED` Ticket, use the `session` fixture, which `client` shares. Keep asserting through HTTP.
- Use `httpx2`, not `httpx`, for `TestClient`. Starlette deprecates `httpx` there.
- Each test uses a session on an open transaction, supplied through `app.dependency_overrides[get_session]` and rolled back afterwards. Don't write teardown for rolled-back data.
- The override wraps each request in `session.begin_nested()`. Without that savepoint nothing flushes, so a deleted Ticket can still be read back and `test_delete_ticket` fails.
- When a request raises, the override calls `session.expire_all()` before re-raising. Rolling back the savepoint undoes the database writes, but an object refreshed by `UPDATE ... RETURNING` keeps its new values in the session's cache, so the next request would read them back.
- Don't assert order by `created_at` inside a rolled-back test. `now()` is the transaction's start time, so every row in the test gets the same value.
- Name files `test_<resource>_api.py` and tests `test_<behaviour>`. Pytest silently skips a function without the `test_` prefix. Assert on status codes and response bodies.
- A test that commits for real skips the override and cleans up after itself. Keep these rare.
- Every migration must pass the downgrade and upgrade round-trip test.

## Aurora

- Mark tests that need AWS with `@pytest.mark.aurora`. `addopts = "-m 'not aurora'"` excludes them by default; run them deliberately with `pytest -m aurora`.
- An Aurora test builds its own engine with `create_iam_engine()`, because the forced `DATABASE_URL` means the module-level `engine` is local.
