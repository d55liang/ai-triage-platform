# Design

Interview-prep notes: what was decided, why, what else was considered, and what it costs. Terms follow [GLOSSARY.md](GLOSSARY.md).

## Overview

AI Triage Platform turns natural-language requests into structured work. A User talks to the Intake Agent; each distinct request becomes a Ticket; Triage matches the Ticket to a predefined Workflow Definition once its Match Confidence clears that definition's Confidence Threshold, which creates a Workflow Run (see §11 and §12). Today only the Ticket API exists: a FastAPI backend persisting to Aurora PostgreSQL.

```text
Client ──HTTP──▶ FastAPI
                  │
                  ▼
          routers/   validation, status codes, KeyError → 404
                  │
                  ▼
          services/  IDs, defaults, business rules
                  │
                  ▼
      repositories/  ORM queries on the caller's session, no commits
                  │
                  ▼
           database.py ──▶ Aurora PostgreSQL Serverless v2 (us-east-2, express config, no VPC)
                           SQLAlchemy over psycopg, IAM auth token per connection,
                           TLS pinned to Amazon Root CA 1; one session per request
```

---

## 1. Layered architecture (router → service → repository)

- **Decision:** three layers. Each one calls only the layer below it.
- **Why:** HTTP concerns, business rules and persistence change for different reasons. Swapping the database client (as the IAM migration does) touches only the repository and `database.py`.
- **Alternatives:** logic inside route handlers (fine for a toy app, but it mixes HTTP and SQL); a full hexagonal / ports-and-adapters design (too much ceremony at this size).
- **Tradeoffs:** some pass-through service functions today (`get_ticket` only calls `fetch_ticket`). Accepted, because the service layer is where Triage logic will go. The database session is the one thing that crosses all three layers: the router receives it from FastAPI and passes it down (see §5, *Session per request*).
- **Soundbite:** "I split routing, business logic and persistence so I could replace the data layer without touching the API. That paid off when I migrated off the Data API."

## 2. Aurora PostgreSQL Serverless v2

- **Decision:** Aurora PostgreSQL 17, Serverless v2, 0–4 ACU, auto-pause after 300 s.
- **Why:** relational data with clear relationships (Ticket → Workflow Run → Workflow Definition); scale-to-zero keeps a personal project cheap; managed backups and IAM integration.
- **Alternatives:** DynamoDB (cheap and serverless, but the data is relational and needs joins); RDS PostgreSQL on a fixed instance (simpler, but it bills 24/7).
- **Tradeoffs:** cold start of several seconds after auto-pause; AWS lock-in for the cluster itself, though the SQL stays standard Postgres.
- **Soundbite:** "My data is relational, so I chose Postgres. Serverless v2 with scale-to-zero means I only pay while I'm actually using it."

## 3. IAM auth tokens instead of the Data API

See [ADR 0001](docs/adr/0001-iam-auth-over-data-api.md). Status: **done**.

- **Decision:** connect directly with `psycopg`, using a short-lived IAM auth token as the password, through SQLAlchemy, with Alembic for migrations.
- **Why:** SQLAlchemy and Alembic need a standard driver. The Data API dialect (`sqlalchemy-aurora-data-api`) is third-party and was last released in Dec 2023. A standard driver also lets the same code run against a local PostgreSQL. IAM tokens expire after 15 minutes, so there is no long-lived database password.
- **Alternatives:** keep the Data API (no networking or pooling to manage, HTTPS from anywhere, but its own typed-value format and a stale SQLAlchemy dialect). On this cluster it isn't actually viable: every Data API call needs a Secrets Manager secret, and express configuration doesn't support one. The first Ticket CRUD version was written against it and never ran. A password stored in Secrets Manager isn't an option on this cluster: express configuration allows IAM auth only (see §4).
- **Tradeoffs:** the app now owns connection pooling and token refresh. A new token must be generated for every *new* connection (SQLAlchemy `do_connect` event); existing connections stay valid after the token expires. Direct connections also need a network path (see §4).
- **Soundbite:** "I moved off the Data API so I could use SQLAlchemy and Alembic with the standard Postgres driver and test locally. IAM database auth gives me short-lived, passwordless credentials."

## 4. Express configuration: internet access gateway, IAM-only auth

- **Decision:** keep the cluster as created with Aurora's **express configuration**. It has no VPC, and clients reach it over the internet through Aurora's managed **internet access gateway**, which accepts **IAM authentication only**.
- **Why:** after leaving the Data API, a laptop needs a direct network path to the database. The gateway already provides one, with no VPN, bastion or security groups to manage. Identity takes the place of network position: every connection needs a 15-minute IAM token, and the database user must have the `rds_iam` role.
- **Alternatives:** a cluster with full configuration inside a VPC, reached through an SSM port-forward or a bastion (private network, but an extra instance and setup, and the AWS org's policies may restrict it); a VPC cluster made publicly accessible with a security group limited to one IP (network-level allowlist, but the IP must be maintained, and it still needs a new cluster).
- **Tradeoffs:**
  - The endpoint is reachable from anywhere on the internet. There is no IP allowlist; protection is IAM auth plus TLS.
  - These settings are fixed: the cluster can never join a VPC, the gateway can't be disabled, and password and Secrets Manager authentication are unavailable.
  - No RDS Proxy or Blue/Green deployments.
  - TLS trust is pinned to Amazon Root CA 1, which the gateway's certificate chains to, committed as `certs/AmazonRootCA1.pem` and verified with `sslmode=verify-full`. The alternatives were the OS trust store (`sslrootcert=system`), which fails because the OpenSSL bundled with `psycopg[binary]` has no usable default store, and the `certifi` bundle (one more dependency, and it trusts ~150 public CAs instead of one). Cost: if AWS ever moves the gateway to another root, the file needs updating (Amazon Root CA 1 is valid until 2038).
  - The RDS Query Editor isn't usable on this account's AWS Free plan, so admin SQL (creating users and databases, grants) runs as `postgres` in AWS CloudShell, launched from the cluster's *Connectivity & security* tab. The Data API can't fill that role either: it needs a Secrets Manager secret, which express clusters don't support.
  - `postgres` on Aurora is not a true superuser. Since PostgreSQL 16, a non-superuser who creates a role can manage it but not act as it, so `CREATE DATABASE ai_triage OWNER triage_app` first needs `GRANT triage_app TO postgres WITH SET TRUE, INHERIT FALSE`.
  - Getting a private network later means a new cluster created with full configuration, plus a data migration.
- **Soundbite:** "My cluster sits behind Aurora's internet access gateway, which only accepts IAM auth. There are no passwords and no VPN, and each connection uses a short-lived token tied to an IAM identity. For production I'd move to a VPC cluster so the database isn't internet-facing at all."

## 5. SQLAlchemy: ORM for CRUD, Core for complex queries

- **Decision:** ORM models and sessions for simple, routine CRUD; SQLAlchemy Core (`select()`, `text()`) for complex queries.
- **Why:** the ORM removes boilerplate (no hand-written row mapping like `_row_to_ticket`). Core keeps full control and readable SQL where queries get complicated, e.g. Triage lookups or reporting.
- **Alternatives:** ORM everywhere (uniform, but complex queries become opaque); Core or raw SQL everywhere (maximum control, but repetitive CRUD).
- **Tradeoffs:** two styles to know. The rule is: CRUD on one table → ORM; joins, aggregates or anything performance-sensitive → Core.
- **Soundbite:** "I use the ORM where it saves boilerplate and Core where I want to see the SQL. Same engine and same transactions, so they mix cleanly."

### Session per request: the caller owns the transaction

- **Decision:** a FastAPI dependency (`get_session`, exposed as `SessionDep`) opens one session per request with `SessionLocal.begin()`, commits when the handler returns and rolls back if it raises. The session is passed router → service → repository. Repositories use it and `flush()` but never commit. Workers will open their own session the same way and call the same repositories.
- **Why:**
  - Several repository calls can be one transaction, e.g. Triage creating a Workflow Run and setting the Ticket to TRIAGED: both or neither.
  - Tests can override the dependency with a session inside a transaction that is rolled back after each test, so every test starts clean with no teardown.
  - Repositories that take a session work for both HTTP requests and queue workers.
  - One connection per request instead of one per repository call.
- **Alternatives:** each repository function opens and commits its own session. Fewer signature changes, but every call is its own transaction, tests can't reach the session, and workers couldn't group calls.
- **Tradeoffs:**
  - Every service and repository signature carries a `session` parameter.
  - The commit happens after the handler returns, so a repository must `flush()` when the response needs database-generated values such as `created_at`.
  - The dependency uses `scope="function"` so the commit runs *before* the response is sent. With FastAPI's default `"request"` scope it would run after, and a failed commit would follow a 201.
  - A request holds its connection until it commits, so no slow external calls (LLM, queue) while a session is active.
- **Soundbite:** "One session per request through a FastAPI dependency, committed before the response goes out. Repositories never commit, so I can compose several calls into one transaction, and in tests I swap in a session that rolls back."

### Table models separate from API models (no SQLModel)

- **Decision:** SQLAlchemy ORM classes (`app/models/orm.py`) describe tables; Pydantic models (`app/models/request.py`, `response.py`) describe the API contract. Response models read ORM objects with `from_attributes=True`.
- **Why:** the storage schema and the API contract change for different reasons. A column can be added without exposing it, and a JSON field can be renamed without a migration.
- **Alternatives:** SQLModel, one class that is both table and Pydantic model. It removes the duplicated field names, but table models skip validation (so request models are still needed), it couples the API to the schema, it is pre-1.0 and maintained largely by one person, and database-specific types (`TIMESTAMPTZ`, server defaults) still go through SQLAlchemy options.
- **Tradeoffs:** field names are written twice, and the types must be kept in step by hand (e.g. `UUID` and `datetime` in both).
- **Soundbite:** "My table models and API models are separate: the database schema and the API contract evolve for different reasons. SQLModel would save a few lines but tie them together."

## 6. Connection pooling vs. Serverless v2 auto-pause

Status: **done**.

- **Decision:** a small pool (`pool_size=2`, `max_overflow=0`) with `pool_pre_ping=True`. On the server, the app user has `idle_session_timeout = '60s'`, so Postgres closes connections that sit idle for a minute. No `pool_recycle`.
- **Why:**
  - Pooling avoids a TLS handshake over the internet on every request.
  - Idle pooled connections stop Serverless v2 from auto-pausing. The server-side timeout closes them, so the cluster can pause while the app is still running.
  - `pool_pre_ping` detects connections closed by the timeout or by a pause and replaces them transparently.
  - `pool_recycle` isn't needed for token expiry: an IAM token only has to be valid when a connection opens, and existing connections stay valid after it expires.
- **Alternatives:** `NullPool` (a new connection per request: auto-pause works trivially, but every request pays for TLS and token generation); `pool_recycle` (client-side, only checked on checkout, so idle connections still hold the cluster awake).
- **Tradeoffs:** the first request after an idle minute pays one reconnect; the first after an auto-pause pays a cold start of several seconds.
- **Soundbite:** "Pooling and scale-to-zero pull in opposite directions. I keep a tiny pool and let Postgres close idle sessions after a minute, with pre-ping to reconnect, so the cluster can still pause while the app runs."

## 7. UUID primary keys generated in the service

- **Decision:** `ticket_id` is a UUIDv4 created in `ticket_service.create_ticket`, stored as a Postgres `UUID`.
- **Why:** IDs can't be guessed or enumerated, they are safe to expose in URLs, and the ID exists before the insert happens.
- **Alternatives:** auto-increment integers (smaller and naturally ordered, but guessable and they leak volume); DB-generated `gen_random_uuid()` (equivalent, but the service no longer owns the ID).
- **Tradeoffs:** 16-byte keys and no natural ordering (use `created_at` for ordering).
- **Soundbite:** "UUIDs so IDs aren't guessable and can be exposed in URLs. Ordering comes from `created_at`."

## 8. UUID validation at the router

- **Decision:** path parameters are typed as `UUID`, so FastAPI returns 422 for malformed IDs before any query runs.
- **Why:** malformed input fails fast with a clear error, and invalid casts never reach the database.
- **Soundbite:** "Validation happens at the edge. A bad ID never costs a database round trip."

## 9. PATCH partial updates with a column allowlist

- **Decision:** `PATCH /tickets/{id}` uses `model_dump(exclude_unset=True)`, and the repository only sets attributes listed in `ALLOWED_COLUMNS` (currently `message`); the ORM emits an `UPDATE` for the changed attributes only.
- **Why:** clients send only the fields they want to change. With raw SQL the allowlist prevented injection through column names. With the ORM, injection isn't possible, and the allowlist instead guarantees that `ticket_id`, `status` and `created_at` can never be changed through `PATCH`, even if the request model grew by mistake. Status is system-managed (§11).
- **Alternatives:** PUT with a full replacement (simpler, but clients must send everything).
- **Tradeoffs:** unknown fields such as `status` are ignored with a 200 rather than rejected; `extra="forbid"` on the request model would turn them into a 422.
- **Soundbite:** "Partial updates via PATCH. The request model and a repository allowlist both limit what can change, so status stays system-managed."

## 10. Testing: local PostgreSQL first, Aurora for what matters

Status: **planned**.

- **Decision:** run simple, fast tests against a local PostgreSQL 17 in Docker. Run the important tests that depend on AWS (IAM auth, connectivity) against Aurora, deliberately and less often.
- **Why:** local tests are free and fast. Aurora tests catch what a local database can't, without paying for every run.
- **Alternatives:** reuse the Homebrew PostgreSQL 18 already running on this machine (no setup, but it breaks the version match and is one more difference to defend).
- **Tradeoffs:** small differences between local Postgres and Aurora can slip through. Mitigated by matching the major version (17) and keeping the Aurora tests for the integration edges. Docker must be running to test.
- **Soundbite:** "Most tests run on a local Postgres for speed and cost. A small set runs against Aurora to cover IAM auth and the cloud-specific behaviour."

### Choosing the engine: an optional `DATABASE_URL`

- **Decision:** `app/database.py` reads an optional `DATABASE_URL`. If it is set, the app uses a plain engine on that URL; if not, it calls `create_iam_engine()`, which owns the Aurora env vars, the RDS client and the `do_connect` token listener.
- **Why:** today `database.py` requires the Aurora variables and builds the IAM engine at import time, so importing the app ties a test to Aurora. One switch also moves Alembic to the local database, because `env.py` already uses `engine`, which makes "migrate locally first" possible.
- **Alternatives:** a lazy `get_engine()` factory (removes import-time side effects, but changes `SessionLocal`, `get_session` and `env.py` for no benefit yet); faking the Aurora env vars in tests (the real engine would still force `verify-full` TLS and fetch IAM tokens).
- **Tradeoffs:** one branch in `database.py`, and `DATABASE_URL` must be set before any `app` import. `tests/conftest.py` hard-sets it rather than using `setdefault`, and `load_dotenv()` doesn't override it, so nothing in a shell or `.env` can point a test run at Aurora.
- **Soundbite:** "The app picks its engine from one optional setting. Production gets IAM auth, tests get a local URL, and the test suite forces that URL so it can't touch Aurora by accident."

### Test harness: real database, rollback per test

- **Decision:**
  - Tests go through HTTP with `TestClient` against the real local database, with no mocks. Repository or service tests are added only for logic HTTP can't reach.
  - `alembic upgrade head` builds the schema once per test run, in a dedicated `ai_triage_test` database.
  - Each test overrides `get_session` with a session on an open transaction that is rolled back afterwards.
  - Three tests sit outside that pattern: one skips the override and goes through the real commit, with its own cleanup; one runs a migration downgrade and upgrade round trip; one, marked `aurora` and excluded by default, runs `SELECT 1` through the IAM engine.
- **Why:** the layers are thin, so mocked tests would mostly repeat the code. Building the schema with Alembic means every run exercises the real migrations, including the enum `CHECK` constraint. Rollback needs no teardown, so a new table adds no cleanup work. The rollback override never commits, so the commit path needs its own test.
- **Alternatives:** `Base.metadata.create_all()` for the schema (faster, but passes even when a migration is missing or wrong); truncating tables after each test (closer to real behaviour, but slower, and every table adds cleanup); deferring Aurora tests (a slightly simpler seam, but leaves IAM auth untested).
- **Tradeoffs:** no test forces a failed commit, so the `scope="function"` ordering isn't proven by a test. The Compose database uses `trust` auth, which keeps any password out of the repo and is safe only because the port binds to loopback and the data is disposable.
- **Soundbite:** "Tests hit a real Postgres through the HTTP API, on a schema built by my actual migrations. Each test rolls back, so they stay isolated with no cleanup code, and one test goes through the real commit so that path is covered too."

## 11. Ticket lifecycle: a status per handoff, ending at Triage

Status: **enum done**; the queue and workers that drive the transitions are planned.

```text
CREATED ──publish──▶ QUEUED ──worker claims──▶ TRIAGING ──match──▶ TRIAGED
   ▲                   ▲                          ├──no match──▶ UNMATCHED
   └ re-publish        └──── timeout / retry ─────┤
     (stuck in                                    └──retries used up──▶ FAILED
      CREATED)
CANCELLED: reachable by User action from any status except FAILED and CANCELLED
```

- **Decision:** seven Ticket Statuses (see `GLOSSARY.md`), one per handoff between the API, the queue and the triage workers. The lifecycle ends at TRIAGED; completion belongs to the Workflow Run, which gets its own status. Stored as `VARCHAR(20)` with a `CHECK` constraint, not a native Postgres enum. Status is system-managed, so `PATCH` can't set it.
- **Why:**
  - Each status is a place a Ticket can get stuck, so each one can be monitored and recovered.
  - **CREATED vs QUEUED** covers the dual-write problem: saving to Postgres and publishing to the queue are two systems, and the publish can fail after the save commits. A Ticket left in CREATED is found and re-published. The standard fix later is a transactional outbox (Ticket and outbox row in one transaction; a separate process publishes).
  - **TRIAGING** lets a worker claim a Ticket idempotently: `UPDATE ... SET status = 'TRIAGING' WHERE ticket_id = :id AND status = 'QUEUED'`. Queues deliver at least once, so only the worker whose update matches a row proceeds. A crashed worker leaves TRIAGING, which a timeout returns to QUEUED.
  - **UNMATCHED** and **FAILED** give the unhappy paths a home instead of leaving Tickets in TRIAGING.
  - Ending at TRIAGED gives each fact one owner. If the Ticket mirrored the Run's outcome, the two could drift.
- **Alternatives:**
  - The Ticket mirrors the Run (`COMPLETED`, `CLOSED`): one field to read, but two sources of truth kept in sync by hand.
  - A native Postgres `ENUM`: also enforced, but removing or renaming a value means re-creating the type.
  - Fewer statuses (`CREATED`, `TRIAGED`): simpler, but stuck and failed Tickets are invisible.
- **Tradeoffs:** "is the User's request done?" needs a join to the Workflow Run, or a value computed at read time. Changing the allowed values needs a hand-written migration, because Alembic autogenerate doesn't detect `CHECK` changes.
- **Soundbite:** "Each Ticket Status is a handoff in the pipeline, so I can see exactly where a Ticket is stuck. CREATED vs QUEUED covers the dual-write problem, and TRIAGING is claimed with a conditional update so duplicate deliveries are harmless. Once triaged, progress belongs to the Workflow Run."

## 12. Intake Agent: tools for platform operations, Triage for domain requests

Status: **planned**.

```text
User message ─▶ Intake Agent (one LLM call per turn, with tools)
                 ├─ new domain request ─▶ create_ticket ─▶ queue ─▶ Triage workers ─▶ Workflow Run
                 ├─ about a Ticket     ─▶ list_tickets / cancel_ticket (synchronous API calls)
                 └─ unclear            ─▶ ask the User
```

- **Decision:** the Intake Agent is an LLM with tool calling. Platform operations (create, list, cancel a Ticket) are tools backed by API endpoints. Domain requests ("order a laptop") become Tickets and go through Triage on asynchronous workers. Rule of thumb: if it changes the platform's own state, it's a tool; if it's work the User wants done, it's a Ticket.
- **Why:**
  - Platform operations are few, fixed in code, and must be instant and exact. Domain requests are many, defined as data by admins, and ambiguous, which is what Match Confidence and Confidence Thresholds are for.
  - Choosing a tool costs nothing extra: it happens in the same LLM call that writes the reply. The expensive matching only runs for extracted Tickets, off the request path.
  - Cancelling is a synchronous call, not a queue message. Workers never receive "cancel"; they respect the status, because every transition is a compare-and-set (`UPDATE ... WHERE status = <expected>`). A worker that claims or finishes a cancelled Ticket matches no row and stops.
  - Single-purpose endpoints (`/cancel` rather than a generic status `PATCH`) are easier for an LLM to call correctly.
- **Alternatives:** model platform operations as Workflow Definitions and triage everything. One mechanism, but a cancel becomes a Ticket about a Ticket, waits on the queue while the target keeps moving, can come back UNMATCHED, and still needs platform code to change statuses.
- **Tradeoffs:** two paths to build and explain. Tool calls are only as good as the model's choice, so the service must still check ownership and allowed transitions: the LLM decides what to call, the service decides what's allowed, and tool calls are never trusted for authorisation.
- **Scaling Triage later:** with many Workflow Definitions, match in two stages. Embedding similarity shortlists a few candidates cheaply; the LLM computes Match Confidence only for the shortlist.
- **Soundbite:** "Platform operations are tools: fast, deterministic, few. Domain requests become Tickets and go through Triage, because matching against an open-ended, admin-defined set of workflows is what actually needs confidence scoring. The database status is the source of truth, and every transition is a compare-and-set, so a cancel can't race with a worker."

## 13. Lint and format: Ruff

Status: **done**.

- **Decision:** Ruff for both linting and formatting, configured in `pyproject.toml`, with line length 100 and rules `E, W, F, I, UP, B, N, SIM, RUF, ANN`. `E501` is ignored because the formatter owns line length. `alembic/versions/` is excluded. Ruff, pytest and httpx stay in the single `requirements.txt` for now.
- **Why:** one fast tool replaces a linter, an import sorter and a formatter. `ANN` turns "type hints on every signature" into a check. Excluding `alembic/versions/` keeps the "never edit an applied migration" rule absolute.
- **Alternatives:** Ruff's default length of 88 (reformats more files with no benefit here) or 120 (leaves long lines alone); adding `TRY`, `PTH`, `C4` and `ASYNC` (they found nothing today, so they wait until needed); a separate `requirements-dev.txt` (keeps dev tools out of production installs, but that doesn't matter until something deploys).
- **Tradeoffs:** Ruff's default import order rewrites the import blocks in 7 files, and production installs include dev tools.
- **Soundbite:** "Ruff handles linting and formatting in one tool, and it enforces the conventions I'd otherwise only write down, like type hints on every signature."

---

## Known gaps

- Cancelling has no endpoint yet. With `status` removed from `PATCH`, it needs a dedicated action (e.g. `POST /tickets/{id}/cancel`).
- `UpdateTicketRequest` fields are typed without `| None` but default to `None`. This is deliberate: Pydantic doesn't validate defaults, so an omitted field is simply unset (and dropped by `exclude_unset=True`), while an explicit `null` is rejected with 422 instead of reaching a `NOT NULL` column and failing with 500. The cost is an annotation that type checkers flag.
- The service layer catches `KeyError` only to re-raise it, wrapped in a second `KeyError`. Ruff doesn't flag it; the blocks are removed in the last commit of the pytest PR, once the 404 tests exist.
- `fastapi`, `uvicorn`, `boto3` and `python_dotenv` in `requirements.txt` are unpinned.
- Nothing exists yet for Conversation, Workflow Definition, Workflow Run or Triage.
