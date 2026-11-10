# AI Triage Platform

@GUIDELINE.md

## Project

AI Triage Platform maps a user's natural-language requests to predefined workflows.

A **User** talks to the **Intake Agent** in a **Conversation**. The Intake Agent extracts each distinct request as a **Ticket**, which is queued for **Triage**. When Triage's **Match Confidence** for a **Workflow Definition** meets that definition's **Confidence Threshold**, it creates a **Workflow Run** pinned to that definition's current **Workflow Definition Version**, and the Ticket becomes `TRIAGED`.

Use the vocabulary in [GLOSSARY.md](../GLOSSARY.md) in code, docs, commits and conversation. Design rationale lives in [DESIGN.md](../DESIGN.md); hard-to-reverse decisions live in [docs/adr/](../docs/adr/).

This is a personal resume project. See *Collaboration mode* in [GUIDELINE.md](GUIDELINE.md).

## Tech stack

| Area | Current | Planned |
|---|---|---|
| Language | Python 3.13 | |
| API | FastAPI, Uvicorn | |
| Validation | Pydantic v2 | |
| Database | Aurora PostgreSQL 17 Serverless v2 (`us-east-2`, express configuration: no VPC, IAM-only internet access gateway); local PostgreSQL 17 in Docker for tests | |
| DB access | SQLAlchemy 2 (ORM + Core) over `psycopg`, IAM auth token per connection | |
| Migrations | Alembic (`alembic/`, runs through the app's engine) | |
| Lint / format | Ruff (`pyproject.toml`) | |
| Tests | pytest, httpx2 (`TestClient`) | |
| CI | GitHub Actions (`.github/workflows/ci.yml`) | |

Technology-specific rules live in [rules/](rules/).

## Layout

```text
app/
  main.py                 FastAPI app, /health, router registration
  database.py             Engine (IAM token per connection, pinned TLS), SessionLocal, Base, get_session
  dependencies.py         FastAPI dependencies (SessionDep)
  models/request.py       Pydantic request bodies
  models/response.py      Pydantic response bodies
  models/orm.py           SQLAlchemy table models
  models/enums.py         StrEnums shared by API and table models (TicketStatus, RequiredInputType)
  routers/                HTTP layer: validation, status codes, error mapping
  services/               Business logic: IDs, defaults, orchestration
  repositories/           Persistence: SQL and row mapping
tests/
  conftest.py             Forces the local DATABASE_URL; migration and client fixtures
  test_tickets_api.py     Ticket API tests through TestClient
  test_workflow_definitions_api.py  Workflow Definition API tests through TestClient
  test_workflow_runs_api.py  Workflow Run tests; creation calls the service directly, since only Triage creates Runs
  test_migrations.py      Downgrade and upgrade round trip
  test_aurora.py          IAM connectivity (marked aurora, excluded by default)
docker-compose.yml        PostgreSQL 17 for tests on 127.0.0.1:5433
.github/workflows/ci.yml  Ruff, alembic check and pytest on every PR
```

## Commands

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload      # http://localhost:8000/docs, /health, /api/tickets
```

```bash
alembic upgrade head                                  # apply migrations (connects to Aurora as triage_app)
alembic revision --autogenerate -m "<what changed>"   # draft a migration from app/models/orm.py; review before applying
alembic upgrade head --sql                            # print the SQL without connecting
```

```bash
# Check for models with no migration, against the local test database. Without DATABASE_URL this connects to Aurora.
DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/ai_triage_test alembic check
```

```bash
ruff check .             # lint; add --fix to apply safe fixes
ruff format .            # format; add --check to verify without writing
```

```bash
docker compose up -d     # start the local test database (Docker must be running)
pytest                   # run the local tests; never touches Aurora
pytest -m aurora         # run the Aurora test deliberately; wakes the cluster
```

Run every command with the venv active (`which alembic` must point into `venv/`); Conda's `(base)` environment otherwise shadows it.

### Environment (`.env`, never committed)

`AWS_REGION`, `DB_HOST`, `DB_PORT`, `DB_USER` (`triage_app`), `DB_NAME` (`ai_triage`). Required (`os.environ[...]`) unless `DATABASE_URL` is set; no password, since each connection gets an IAM auth token.

`DATABASE_URL` is optional and selects a plain engine instead of the IAM one (see `DESIGN.md` §10). `tests/conftest.py` always sets it to the local test database.

## Current status

- **Done:** Ticket CRUD API (`/api/tickets`) persisting to Aurora through SQLAlchemy with IAM auth tokens and one session per request; Ticket cancel endpoint (see `DESIGN.md` §11); `Ticket` ORM model, Ticket Status enum, Alembic with the first migration ([ADR 0001](../docs/adr/0001-iam-auth-over-data-api.md)); Ruff lint and format setup (see `DESIGN.md` §13); pytest setup with a local PostgreSQL 17 (see `DESIGN.md` §10); GitHub Actions CI (see `DESIGN.md` §14); Workflow Definition API with immutable versions, publishing and disable/enable (`DESIGN.md` §15, [ADR 0002](../docs/adr/0002-immutable-workflow-definition-versions.md)).
- **In progress:** Workflow Run. Design done (`DESIGN.md` §17); implementation in three PRs: table, `create_workflow_run` for Triage and read routes (merged); Required Input submission (in review); cancelling a TRIAGED Ticket together with its Run, and the 409 for deleting a Ticket that has one. Executing Steps is a later milestone.
- **Next:** Conversation (including the Intake Agent turn that collects Required Inputs, `DESIGN.md` §16) and Triage.

Update this section when a milestone starts or lands.

## Coding style

Follow the existing code. In particular:

- **Layers:** router → service → repository. Each layer calls only the one below it. Routers never touch the database; repositories never raise HTTP errors.
- **Sessions:** the caller owns the transaction. Routers take `session: SessionDep` and pass it as the first argument to the service, which passes it to the repository. Repositories never commit (see `rules/postgres.md`).
- **Naming:** files `<resource>_router.py`, `<resource>_service.py`, `<resource>_repository.py`. Router handlers end in `_api`. Service verbs are `create/get/update/delete`, plus domain actions such as `cancel`; repository verbs are `save/fetch/modify/remove`.
- **Models:** request bodies in `models/request.py` (`<Action><Resource>Request`), responses in `models/response.py` (`<Resource>Item`, list wrapper `<Resource>sResponse` with a `data` field). Every field is `Annotated[..., Field(description=...)]`. Table models live in `models/orm.py`, one class per table named after the resource (`Ticket`). Keep table and API models separate; don't use SQLModel (see `DESIGN.md` §5).
- **Errors:** repositories raise `KeyError` when a row is missing and `ValueError` when its status doesn't allow a transition; routers translate them to `HTTPException(404)` and `HTTPException(409)` with `raise ... from e`.
- **Routes:** always set `response_model` and `status_code`. Type path IDs as `UUID` so FastAPI rejects malformed IDs with 422.
- **SQL:** always parameterised. Dynamic column names come only from an allowlist.
- **Imports:** stdlib, third-party, then `app.*`, separated by a blank line.
- **Type hints** on every function signature.

## PR & commit language

**Commits:** [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`, imperative mood, lowercase, no trailing period, ≤ 72 characters. Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`. Scope is the resource or layer, e.g. `feat(tickets): …`, `refactor(db): …`.

**PR title:** same format as a commit.

**PR body:** use [.github/pull_request_template.md](../.github/pull_request_template.md): *Summary*, *Why*, *Changes*, *How to test*, *Design notes / tradeoffs*, *Docs updated*. Plain English, present tense, no filler. Link the `DESIGN.md` section or ADR when the PR reflects a design decision.

## Testing strategy

1. **Local PostgreSQL first** for fast tests: API tests through `TestClient` with no mocks, plus migrations. Each test rolls back; the schema comes from Alembic.
2. **Aurora** only for the important tests that depend on AWS behaviour, e.g. IAM token auth and connectivity. Marked `aurora`, excluded by default, and run deliberately to save cost.

See `DESIGN.md` §10 and `rules/pytest.md`.
