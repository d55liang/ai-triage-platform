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
| Queue | Amazon SQS through `boto3`, fed by a transactional outbox; queues `triage` and `triage-dlq` in `us-east-2`; ElasticMQ in Docker locally and in CI | |
| Infrastructure | AWS CloudFormation (`infra/`), deployed from CloudShell as root | |
| Triage Providers | Anthropic API through `anthropic` and Gemini API through `google-genai` (async clients, structured outputs) | |

Technology-specific rules live in [rules/](rules/).

## Layout

```text
app/
  main.py                 FastAPI app, /health, router registration
  database.py             Engine (IAM token per connection, pinned TLS), SessionLocal, Transaction (what workers take to open one), Base, get_session
  queue.py                SQS client (ElasticMQ when SQS_ENDPOINT_URL is set), queue URLs, batch send, receive one and delete
  dependencies.py         FastAPI dependencies (SessionDep)
  models/request.py       Pydantic request bodies
  models/response.py      Pydantic response bodies
  models/orm.py           SQLAlchemy table models
  models/enums.py         StrEnums shared by API and table models (TicketStatus, OutboxEventType, RequiredInputType)
  models/triage.py        What a Triage Provider receives and returns (Candidate, MatchResult)
  models/queue.py         Queue message envelopes as consumers validate them (TicketQueuedMessage)
  routers/                HTTP layer: validation, status codes, error mapping
  services/               Business logic: IDs, defaults, orchestration
  repositories/           Persistence: SQL and row mapping
  providers/              TriageProvider Protocol; triage_prompt.py: the shared prompt, score schema and parser; one adapter per SDK (anthropic_provider.py, gemini_provider.py); factory.py: build_providers() from TRIAGE_PROVIDERS
  workers/relay.py        Outbox relay process: publishes unpublished outbox events to SQS
  workers/triage.py       Triage worker process: claims, scores and finishes one queued Ticket per message
  workers/dlq.py          DLQ consumer process: moves each Ticket whose retries are used up to FAILED
tests/
  conftest.py             Forces the local DATABASE_URL and ElasticMQ; migration, client, empty_queues and transaction fixtures
  fakes.py                FakeProvider, shared by the Triage service and worker tests
  test_tickets_api.py     Ticket API tests through TestClient
  test_workflow_definitions_api.py  Workflow Definition API tests through TestClient
  test_workflow_runs_api.py  Workflow Run tests; creation calls the service directly, since only Triage creates Runs
  test_outbox_relay.py    Relay publishing against ElasticMQ; calls the outbox service directly
  test_queue.py           Receiving and deleting messages against ElasticMQ
  test_triage_service.py  Triage steps (claim, release, scoring with fake providers, finishing) called directly
  test_triage_worker.py   The worker's handling of one message, with fake providers and savepoints for its transactions
  test_dlq_worker.py      The DLQ consumer's handling of one dead letter, including a slow worker finishing late
  test_triage_prompt.py   The shared prompt, score schema and answer parsing; pure, no database
  test_anthropic_provider.py  The Anthropic adapter's request and answer handling; one live call marked llm
  test_gemini_provider.py  The Gemini adapter's config and answer handling; one live call marked llm
  test_provider_factory.py  Building providers from TRIAGE_PROVIDERS; no API calls
  test_migrations.py      Downgrade and upgrade round trip
  test_aurora.py          IAM connectivity (marked aurora, excluded by default)
  test_sqs_aws.py         The real queues' settings and the IAM policy's permissions (marked aws, excluded by default)
docker-compose.yml        PostgreSQL 17 on 127.0.0.1:5433 and ElasticMQ on 127.0.0.1:9324, for tests
elasticmq.conf            Local queues: triage and its DLQ, as in AWS
infra/triage-queues.yaml  CloudFormation: the AWS queues and the ai-triage-sqs IAM policy for the app's user
.github/workflows/ci.yml  Ruff, alembic check and pytest on every PR
```

## Commands

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload      # http://localhost:8000/docs, /health, /api/tickets
python -m app.workers.relay        # outbox relay: publishes saved events to SQS; Ctrl-C stops it after the current batch
python -m app.workers.triage       # triage worker: needs TRIAGE_PROVIDERS and the providers' API keys; Ctrl-C stops it after the current message (up to 20 s)
python -m app.workers.dlq          # DLQ consumer: moves Tickets whose retries are used up to FAILED; Ctrl-C as above
```

```bash
alembic upgrade head                                  # apply migrations (connects to Aurora as triage_app)
alembic revision --autogenerate -m "<what changed>"   # draft a migration from app/models/orm.py; review before applying
alembic upgrade head --sql                            # print the SQL without connecting
```

```bash
# In AWS CloudShell as root, never from the laptop: the app's user can't create these. Steps in README.md.
aws cloudformation deploy --template-file triage-queues.yaml --stack-name ai-triage-queues --parameter-overrides AppUserName=<app IAM user> --capabilities CAPABILITY_NAMED_IAM --no-execute-changeset
aws cloudformation execute-change-set --change-set-name <change-set-arn>   # only after reviewing it
aws cloudformation describe-stacks --stack-name ai-triage-queues --query "Stacks[0].Outputs"   # queue URLs for .env
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
docker compose up -d     # start the local test database and ElasticMQ (Docker must be running)
pytest                   # run the local tests; never touches Aurora
pytest -m aurora         # run the Aurora test deliberately; wakes the cluster
pytest -m llm            # run the live Triage Provider tests deliberately; costs a little
pytest -m aws            # check the real SQS queues and permissions; no workers may be running against AWS
```

Run every command with the venv active (`which alembic` must point into `venv/`); Conda's `(base)` environment otherwise shadows it.

### Environment (`.env`, never committed)

`AWS_REGION`, `DB_HOST`, `DB_PORT`, `DB_USER` (`triage_app`), `DB_NAME` (`ai_triage`). Required (`os.environ[...]`) unless `DATABASE_URL` is set; no password, since each connection gets an IAM auth token.

`DATABASE_URL` is optional and selects a plain engine instead of the IAM one (see `DESIGN.md` §10). `tests/conftest.py` always sets it to the local test database.

`TRIAGE_QUEUE_URL` and `TRIAGE_DLQ_URL` are required by anything that imports `app/queue.py` (the relay and the workers; not the API). `SQS_ENDPOINT_URL` is optional and points boto3 at ElasticMQ instead of AWS. For AWS, leave it unset and take both URLs from the `ai-triage-queues` stack's outputs. For local runs: `SQS_ENDPOINT_URL=http://127.0.0.1:9324`, `TRIAGE_QUEUE_URL=http://127.0.0.1:9324/000000000000/triage` and `TRIAGE_DLQ_URL=http://127.0.0.1:9324/000000000000/triage-dlq`. `tests/conftest.py` always sets all three, and `AWS_REGION`.

`ANTHROPIC_API_KEY` and `GEMINI_API_KEY` are read by each SDK itself when `AnthropicProvider` or `GeminiProvider` is built; only the triage worker and `pytest -m llm` need them. `GeminiProvider` raises without its key, and `GOOGLE_API_KEY`, if set, takes priority over `GEMINI_API_KEY`.

`TRIAGE_PROVIDERS` is required by `build_providers()`, which the triage worker calls at startup: a comma-separated list of provider names, e.g. `anthropic,gemini`, or one name to run with a single key locally. An empty list, an unknown name or a repeat raises `ValueError`.

## Current status

- **Done:** Ticket CRUD API (`/api/tickets`) persisting to Aurora through SQLAlchemy with IAM auth tokens and one session per request; Ticket cancel endpoint (see `DESIGN.md` §11); `Ticket` ORM model, Ticket Status enum, Alembic with the first migration ([ADR 0001](../docs/adr/0001-iam-auth-over-data-api.md)); Ruff lint and format setup (see `DESIGN.md` §13); pytest setup with a local PostgreSQL 17 (see `DESIGN.md` §10); GitHub Actions CI (see `DESIGN.md` §14); Workflow Definition API with immutable versions, publishing and disable/enable (`DESIGN.md` §15, [ADR 0002](../docs/adr/0002-immutable-workflow-definition-versions.md)). Workflow Runs: one per Ticket, pinned to a version, with Required Input submission and cancelling through the Ticket (`DESIGN.md` §17); executing Steps is a later milestone. Triage (`DESIGN.md` §18, [ADR 0003](../docs/adr/0003-consensus-triage.md)), in five PRs: transactional outbox and relay, removing CREATED; the Triage decision with consensus across Triage Providers; the Anthropic and Gemini Triage Providers; the triage worker and DLQ consumer; the AWS queues and their IAM policy as a CloudFormation stack, deployed in `us-east-2`.
- **In progress:** nothing.
- **Next:** Conversation and the Intake Agent (`DESIGN.md` §19), including the turn that collects Required Inputs (§16); its design is in §19 but hasn't been grilled into PRs yet. Then an offline labelled evaluation set that measures each Triage Provider's accuracy.

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
2. **Local ElasticMQ** for everything that sends or receives; `conftest.py` forces it, so no default test can reach AWS.
3. **Deliberate tests**, excluded by default (`addopts` in `pyproject.toml`) and out of CI, only for behaviour local services can't show:

   | Marker | Tests | Checks | Needs |
   |---|---|---|---|
   | `aurora` | `test_aurora.py` (1) | IAM token auth and TLS to the real cluster | `.env` DB variables; wakes the cluster |
   | `llm` | `test_anthropic_provider.py`, `test_gemini_provider.py` (1 each) | One live scoring call per Triage Provider | API keys; costs a fraction of a cent |
   | `aws` | `test_sqs_aws.py` (4) | Real queue settings match `elasticmq.conf`; the IAM policy allows the app's calls | AWS credentials; no workers running against AWS |

   All three still need Docker, because the migration fixture runs for every session.

See `DESIGN.md` §10 and `rules/pytest.md`.
