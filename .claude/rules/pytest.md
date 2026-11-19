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

- Tests use ElasticMQ from `docker-compose.yml` on `127.0.0.1:9324`. `tests/conftest.py` hard-sets `SQS_ENDPOINT_URL`, `TRIAGE_QUEUE_URL`, `TRIAGE_DLQ_URL` and `AWS_REGION` next to `DATABASE_URL`, so no test can reach AWS.
- The queues aren't rolled back with the database. Tests that send or receive request the `empty_queues` fixture (`pytestmark = pytest.mark.usefixtures("empty_queues")`), which purges both queues before and after each test.
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

- Mark tests that need AWS with `@pytest.mark.aurora`. `addopts = "-m 'not aurora and not llm'"` excludes them by default; run them deliberately with `pytest -m aurora`.
- An Aurora test builds its own engine with `create_iam_engine()`, because the forced `DATABASE_URL` means the module-level `engine` is local.

## LLM providers

- Plain `pytest` and CI never call an LLM. Test each Triage Provider adapter through its pure functions (request building, answer reading), with responses built from the SDK's own types (`Message.model_validate({...})`, `GenerateContentResponse.model_validate({...})`), not hand-rolled fakes.
- One small live test per provider is marked `@pytest.mark.llm` and runs only with `pytest -m llm`. It needs the provider's API key in `.env` and costs real money, so keep it to one call with two candidates.
- Tests of the Triage service and worker use `FakeProvider` from `tests/fakes.py`, never a real adapter.
- Worker tests pass `handle_message` a transaction factory that yields the test session inside `begin_nested()`, so each of the worker's commits is a savepoint and the test still rolls back.
