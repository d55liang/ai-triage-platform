# AI Triage Platform

@GUIDELINE.md

## Project

AI Triage Platform maps a user's natural-language requests to predefined workflows.

A **User** talks to the **Intake Agent** in a **Conversation**. The Intake Agent extracts each distinct request as a **Ticket**, which is queued for **Triage**. When Triage's **Match Confidence** for a **Workflow Definition** meets that definition's **Confidence Threshold**, it creates a **Workflow Run** of that definition, and the Ticket becomes `TRIAGED`.

Use the vocabulary in [GLOSSARY.md](../GLOSSARY.md) in code, docs, commits and conversation. Design rationale lives in [DESIGN.md](../DESIGN.md); hard-to-reverse decisions live in [docs/adr/](../docs/adr/).

This is a personal resume project. See *Collaboration mode* in [GUIDELINE.md](GUIDELINE.md).

## Tech stack

| Area | Current | Planned |
|---|---|---|
| Language | Python 3.13 | |
| API | FastAPI, Uvicorn | |
| Validation | Pydantic v2 | |
| Database | Aurora PostgreSQL 17 Serverless v2 (`us-east-2`, express configuration: no VPC, IAM-only internet access gateway) | Local PostgreSQL for simple tests |
| DB access | Raw SQL via the RDS Data API (`boto3` `rds-data`) | SQLAlchemy 2 (ORM + Core) over `psycopg` with IAM auth tokens |
| Migrations | Alembic (`alembic/`, runs through the app's engine) | |
| Lint / format | None | Ruff |
| Tests | None | pytest |

Technology-specific rules live in [rules/](rules/).

## Layout

```text
app/
  main.py                 FastAPI app, /health, router registration
  database.py             Database client (currently Data API execute_sql)
  models/request.py       Pydantic request bodies
  models/response.py      Pydantic response bodies
  models/orm.py           SQLAlchemy table models
  models/enums.py         StrEnums shared by API and table models (TicketStatus)
  routers/                HTTP layer: validation, status codes, error mapping
  services/               Business logic: IDs, defaults, orchestration
  repositories/           Persistence: SQL and row mapping
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

Run every command with the venv active (`which alembic` must point into `venv/`); Conda's `(base)` environment otherwise shadows it.

Not set up yet (do not claim these work): `ruff check .`, `ruff format .`, `pytest`.

### Environment (`.env`, never committed)

Current: `AWS_REGION`, `DB_CLUSTER_ARN`, `DB_SECRET_ARN`, `DB_NAME`.
After the IAM migration: `AWS_REGION`, `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_NAME`.

## Current status

- **Done:** Ticket CRUD API (`/api/tickets`): routes, service and repository. It was written against the Data API, which can't authenticate to this cluster (no Secrets Manager secret on an express cluster), so it has never persisted to Aurora and the `tickets` table doesn't exist yet.
- **In progress:** migrate the data layer from the Data API to IAM auth tokens with SQLAlchemy, `psycopg` and Alembic ([ADR 0001](../docs/adr/0001-iam-auth-over-data-api.md)). Done so far: database `ai_triage` owned by IAM-auth user `triage_app`; SQLAlchemy engine with IAM tokens and pinned TLS; `Ticket` ORM model and Ticket Status enum; Alembic set up, `tickets` table created by the first migration. Left: move the repository to SQLAlchemy, fix `TicketItem` types, remove the Data API code and env vars.
- **Next:** Ruff and pytest setup; cancel endpoint for Tickets; Conversation, Workflow Definition, Workflow Run and Triage.

Update this section when a milestone starts or lands.

## Coding style

Follow the existing code. In particular:

- **Layers:** router → service → repository. Each layer calls only the one below it. Routers never touch the database; repositories never raise HTTP errors.
- **Naming:** files `<resource>_router.py`, `<resource>_service.py`, `<resource>_repository.py`. Router handlers end in `_api`. Service verbs are `create/get/update/delete`; repository verbs are `save/fetch/modify/remove`.
- **Models:** request bodies in `models/request.py` (`<Action><Resource>Request`), responses in `models/response.py` (`<Resource>Item`, list wrapper `<Resource>sResponse` with a `data` field). Every field is `Annotated[..., Field(description=...)]`. Table models live in `models/orm.py`, one class per table named after the resource (`Ticket`). Keep table and API models separate; don't use SQLModel (see `DESIGN.md` §5).
- **Errors:** repositories raise `KeyError` when a row is missing; routers translate it to `HTTPException(404)` with `raise ... from e`.
- **Routes:** always set `response_model` and `status_code`. Type path IDs as `UUID` so FastAPI rejects malformed IDs with 422.
- **SQL:** always parameterised. Dynamic column names come only from an allowlist.
- **Imports:** stdlib, third-party, then `app.*`, separated by a blank line.
- **Type hints** on every function signature.

## PR & commit language

**Commits:** [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`, imperative mood, lowercase, no trailing period, ≤ 72 characters. Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`. Scope is the resource or layer, e.g. `feat(tickets): …`, `refactor(db): …`.

**PR title:** same format as a commit.

**PR body:** use [.github/pull_request_template.md](../.github/pull_request_template.md): *Summary*, *Why*, *Changes*, *How to test*, *Design notes / tradeoffs*, *Docs updated*. Plain English, present tense, no filler. Link the `DESIGN.md` section or ADR when the PR reflects a design decision.

## Testing strategy (planned)

1. **Local PostgreSQL first** for simple, fast tests: repository queries, migrations, service logic.
2. **Aurora** only for the important tests that depend on AWS behaviour, e.g. IAM token auth and connectivity. Run them deliberately, to save cost.
