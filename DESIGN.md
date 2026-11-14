# Design

Interview-prep notes: what was decided, why, what else was considered, and what it costs. Terms follow [GLOSSARY.md](GLOSSARY.md).

## Overview

AI Triage Platform turns natural-language requests into structured work. A User talks to the Intake Agent; each distinct request becomes a Ticket; Triage matches the Ticket to a predefined Workflow Definition once its Match Confidence clears that definition's Confidence Threshold, which creates a Workflow Run (see §11, §12 and §15–§19). Today the Ticket and Workflow Definition APIs exist: a FastAPI backend persisting to Aurora PostgreSQL.

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
- **Why:** relational data with clear relationships (Ticket → Workflow Run → Workflow Definition Version → Workflow Definition); scale-to-zero keeps a personal project cheap; managed backups and IAM integration.
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

Status: **done**.

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
  - Each test overrides `get_session` with a session on an open transaction that is rolled back afterwards. Each request inside it runs in a savepoint, which stands in for the real commit: it flushes on success and undoes only that request on failure.
  - Three tests sit outside that pattern: one skips the override and goes through the real commit, with its own cleanup; one runs a migration downgrade and upgrade round trip; one, marked `aurora` and excluded by default, runs `SELECT 1` through the IAM engine.
- **Why:** the layers are thin, so mocked tests would mostly repeat the code. Building the schema with Alembic means every run exercises the real migrations, including the enum `CHECK` constraint. Rollback needs no teardown, so a new table adds no cleanup work. The rollback override never commits, so the commit path needs its own test.
- **Alternatives:** `Base.metadata.create_all()` for the schema (faster, but passes even when a migration is missing or wrong); truncating tables after each test (closer to real behaviour, but slower, and every table adds cleanup); deferring Aurora tests (a slightly simpler seam, but leaves IAM auth untested).
- **Tradeoffs:** no test forces a failed commit, so the `scope="function"` ordering isn't proven by a test. The Compose database uses `trust` auth, which keeps any password out of the repo and is safe only because the port binds to loopback and the data is disposable.
- **Soundbite:** "Tests hit a real Postgres through the HTTP API, on a schema built by my actual migrations. Each test rolls back, so they stay isolated with no cleanup code, and one test goes through the real commit so that path is covered too."

## 11. Ticket lifecycle: a status per handoff, ending at Triage

Status: **enum and cancelling done**; the outbox, SQS and Triage workers that drive the other transitions are designed in §18. CREATED is being removed (see *Why*), and UNMATCHED is no longer final: after the User clarifies, the same Ticket is queued again.

```text
insert + outbox row ─▶ QUEUED ──worker claims──▶ TRIAGING ──every provider agrees──▶ TRIAGED
                          ▲                         ├──no agreed match──▶ UNMATCHED ──User clarifies──┐
                          ├── SQS redelivery ───────┤                                                 │
                          │   (stale claim)         └──DLQ after 3 tries──▶ FAILED                    │
                          └───────────────────────────────────────────────────────────────────────────┘
CANCELLED: reachable by User action from QUEUED, TRIAGING, UNMATCHED and TRIAGED
           (from TRIAGED, its Workflow Run is cancelled too, unless it has finished; see §17)
```

- **Decision:** six Ticket Statuses (see `GLOSSARY.md`), one per handoff between the API, the queue and the triage workers. The lifecycle ends at TRIAGED; completion belongs to the Workflow Run, which gets its own status. Stored as `VARCHAR(20)` with a `CHECK` constraint, not a native Postgres enum. Status is system-managed, so `PATCH` can't set it.
- **Why:**
  - Each status is a place a Ticket can get stuck, so each one can be monitored and recovered.
  - **Why CREATED existed, and why it goes:** saving to Postgres and publishing to the queue are two systems, and the publish can fail after the save commits. CREATED marked "saved, publish not confirmed" so a sweeper could re-publish it. That design also had a race: a worker could receive the message before CREATED → QUEUED committed, find no QUEUED row and drop it. The transactional outbox (§18) makes publishing guaranteed, so a Ticket is inserted as QUEUED with its outbox row in one transaction, and nothing changes its status after publishing. Removing the value needs a hand-written `CHECK` migration.
  - **TRIAGING** lets a worker claim a Ticket idempotently: `UPDATE ... SET status = 'TRIAGING' WHERE ticket_id = :id AND status = 'QUEUED'`. Queues deliver at least once, so only the worker whose update matches a row proceeds. A crashed worker leaves TRIAGING, which the next SQS delivery takes over once the claim is stale (§18).
  - **UNMATCHED** and **FAILED** give the unhappy paths a home instead of leaving Tickets in TRIAGING.
  - Ending at TRIAGED gives each fact one owner. If the Ticket mirrored the Run's outcome, the two could drift.
- **Alternatives:**
  - The Ticket mirrors the Run (`COMPLETED`, `CLOSED`): one field to read, but two sources of truth kept in sync by hand.
  - A native Postgres `ENUM`: also enforced, but removing or renaming a value means re-creating the type.
  - Fewer statuses (`QUEUED`, `TRIAGED`): simpler, but stuck and failed Tickets are invisible.
  - Keeping CREATED with the outbox (the relay moves it to QUEUED after sending): the status records publishing, but the worker-before-update race returns, so workers must claim from CREATED too.
- **Tradeoffs:** "is the User's request done?" needs a join to the Workflow Run, or a value computed at read time. Changing the allowed values needs a hand-written migration, because Alembic autogenerate doesn't detect `CHECK` changes.
- **Soundbite:** "Each Ticket Status is a handoff in the pipeline, so I can see exactly where a Ticket is stuck. The outbox covers the dual-write problem, and TRIAGING is claimed with a conditional update so duplicate deliveries are harmless. Once triaged, progress belongs to the Workflow Run."

### Cancelling: a compare-and-set in one request

- **Decision:** `POST /tickets/{id}/cancel` calls `modify_ticket_status`, a compare-and-set: `UPDATE ... WHERE ticket_id = :id AND status IN (...) RETURNING ...`. The service owns the allowed statuses. A missing Ticket returns 404. A `FAILED` Ticket, or a `TRIAGED` one whose Workflow Run is COMPLETED or FAILED, returns 409 through a built-in `ValueError`. Cancelling a `CANCELLED` Ticket returns 200, because `CANCELLED` is one of the allowed statuses.
- **Why:**
  - A read followed by a write has a race: a worker could commit `TRIAGED` in between and the cancel would overwrite it. Here the database checks the status and writes it in one statement. Under `READ COMMITTED`, a cancel that meets an uncommitted worker update waits, re-checks the committed status, then matches no row.
  - `TRIAGED` was left out until Workflow Runs existed, because a status-only cancel couldn't cancel the Run. It joined the allowed statuses in the change that cancels the Run too (§17).
  - A retry after a lost response should succeed, because the caller's goal is already met.
  - `status` stays out of `ALLOWED_COLUMNS`, so `PATCH` still can't change it.
  - Cancelling is `POST` because it's a domain command with its own transition rules, not a client-supplied change. It needs no body, and the server decides whether it's allowed.
- **What workers must do:** cancelling only protects a Ticket if workers also use compare-and-set. Claiming, finishing and the timeout back to `QUEUED` each check the expected status. The `TRIAGED` update and the Workflow Run insert share one transaction, and a worker that matches no row creates no Run.
- **Alternatives:** `PATCH /tickets/{id}` with `{"status": "CANCELLED"}` (one fewer route, but it implies clients can set a system-managed field, and every other status value would need rejecting); `PATCH` or `PUT` on `/tickets/{id}/cancel` (no field to change and no representation to replace, so the verb means nothing); `SELECT ... FOR UPDATE`, then check and set (plain ORM, and one read tells 404 from 409, but it breaks the rule that every transition is a compare-and-set); returning 409 on a repeat cancel (stricter, but reports a failure for something that succeeded); a custom exception (more precise, but one more class where `ValueError` mirrors the `KeyError` convention).
- **Tradeoffs:** when no row matches, a second read separates 404 from 409. `CANCELLED` in the allowed list needs a comment, and a repeat cancel writes the row again. `POST` isn't idempotent by HTTP definition, so safe retries are a promise of this API, and generic clients and proxies won't retry it automatically. A stray `ValueError` from below the service would become a 409, which the narrow `try` keeps unlikely.
- **Soundbite:** "Cancel is one conditional `UPDATE`, so the database decides who wins a race with a worker. If the worker commits first, the cancel gets a 409. If the cancel commits first, the worker matches no row and never creates a Workflow Run. It's a `POST` because status is system-managed: cancel is a command with its own rules, not a field the client edits, and I made it behave idempotently so retries are safe."

## 12. Intake Agent: tools for platform operations, Triage for domain requests

Status: **planned**.

```text
User Message ─▶ Intake Agent (a bounded tool-calling loop per turn)
                 ├─ new domain request ─▶ create_ticket ─▶ queue ─▶ Triage workers ─▶ Workflow Run
                 ├─ about a Ticket     ─▶ list_tickets / cancel_ticket (synchronous API calls)
                 └─ unclear            ─▶ ask the User
```

- **Decision:** the Intake Agent is an LLM with tool calling. A turn is a loop written in the service, not one call: the model asks for a tool, the service runs it and returns the result, and the model continues until it writes its reply, with a cap of about five iterations. It replies synchronously, without streaming. Platform operations (create, list, cancel a Ticket) are tools backed by API endpoints. Domain requests ("order a laptop") become Tickets and go through Triage on asynchronous workers. Rule of thumb: if it changes the platform's own state, it's a tool; if it's work the User wants done, it's a Ticket.
- **Why:**
  - Platform operations are few, fixed in code, and must be instant and exact. Domain requests are many, defined as data by admins, and ambiguous, which is what Match Confidence and Confidence Thresholds are for.
  - Choosing a tool happens inside the turn's loop. The expensive matching runs only for extracted Tickets, on workers, off the request path.
  - Cancelling is a synchronous call, not a queue message. Workers never receive "cancel"; they respect the status, because every transition is a compare-and-set (`UPDATE ... WHERE status = <expected>`). A worker that claims or finishes a cancelled Ticket matches no row and stops.
  - Single-purpose endpoints (`/cancel` rather than a generic status `PATCH`) are easier for an LLM to call correctly.
- **Alternatives:** model platform operations as Workflow Definitions and triage everything. One mechanism, but a cancel becomes a Ticket about a Ticket, waits on the queue while the target keeps moving, can come back UNMATCHED, and still needs platform code to change statuses.
- **Tradeoffs:** two paths to build and explain. Tool calls are only as good as the model's choice, so the service must still check ownership and allowed transitions: the LLM decides what to call, the service decides what's allowed, and tool calls are never trusted for authorisation.
- **LLM providers:** the Intake Agent uses the Anthropic API. Triage uses several Triage Providers and needs them to agree (§18, [ADR 0003](docs/adr/0003-consensus-triage.md)). Prompts are built by dynamic context injection: the current version of each enabled Workflow Definition, and for the Intake Agent the Conversation's current state, is assembled at runtime (§15, §19). Prompt engineering (role, task, context, output contract, temperature) is a later pass.
- **Scaling Triage later:** with many Workflow Definitions, match in two stages. Embedding similarity shortlists a few candidates cheaply; the LLM computes Match Confidence only for the shortlist.
- **Soundbite:** "Platform operations are tools: fast, deterministic, few. Domain requests become Tickets and go through Triage, because matching against an open-ended, admin-defined set of workflows is what actually needs confidence scoring. The database status is the source of truth, and every transition is a compare-and-set, so a cancel can't race with a worker."

## 13. Lint and format: Ruff

Status: **done**.

- **Decision:** Ruff for both linting and formatting, configured in `pyproject.toml`, with line length 100 and rules `E, W, F, I, UP, B, N, SIM, RUF, ANN`. `E501` is ignored because the formatter owns line length. `alembic/versions/` is excluded. Ruff, pytest and httpx2 stay in the single `requirements.txt` for now.
- **Why:** one fast tool replaces a linter, an import sorter and a formatter. `ANN` turns "type hints on every signature" into a check. Excluding `alembic/versions/` keeps the "never edit an applied migration" rule absolute.
- **Alternatives:** Ruff's default length of 88 (reformats more files with no benefit here) or 120 (leaves long lines alone); adding `TRY`, `PTH`, `C4` and `ASYNC` (they found nothing today, so they wait until needed); a separate `requirements-dev.txt` (keeps dev tools out of production installs, but that doesn't matter until something deploys).
- **Tradeoffs:** Ruff's default import order rewrites the import blocks in 7 files, and production installs include dev tools.
- **Soundbite:** "Ruff handles linting and formatting in one tool, and it enforces the conventions I'd otherwise only write down, like type hints on every signature."

## 14. CI: GitHub Actions on every PR

Status: **done**.

- **Decision:**
  - `.github/workflows/ci.yml` runs on `pull_request` to `main` and `push` to `main`, with no path filters. `workflow_dispatch` also allows a manual run.
  - Two jobs. `lint` runs `ruff check .` and `ruff format --check .`. `test` starts Postgres with `docker compose up -d --wait`, then runs `alembic upgrade head`, `alembic check` and `pytest`.
  - The `test` job sets `DATABASE_URL` in `env:` for the Alembic steps, because `tests/conftest.py` only covers pytest.
  - Aurora stays out of CI, so GitHub holds no AWS credentials.
  - The workflow has `permissions: contents: read`, `timeout-minutes: 10` and major-version action tags.
  - All of `requirements.txt` is pinned, so CI installs what runs locally.
  - The repo goes public so a ruleset can protect `main`: PR required with 0 approvals, `lint` and `test` required, force pushes blocked, no bypass actors.
- **Why:** two jobs mean a formatting failure can't hide test results, and `lint` doesn't need a database. Compose keeps one definition of the test database, so CI can't drift from local. `alembic check` catches an ORM change with no migration, which the tests can miss if nothing touches that column. Without a ruleset, a red check is only advice.
- **Alternatives:** one job with sequential steps (simpler, but the first failure hides the rest); a GitHub `services:` block (the common pattern, but it repeats the image, port, database and auth settings); a separate `migrations` job (reports on its own, but needs a second Postgres); running `pytest -m aurora` in CI (needs an OIDC role, and wakes the cluster on every PR); pinning actions to commit SHAs (safer, but more upkeep, and CI holds no secrets); GitHub Pro (protection on a private repo, but paid).
- **Tradeoffs:** a failed `alembic check` skips `pytest` for that run, and a failed `ruff check` skips the format check. The local database URL appears in both the workflow and `conftest.py`. `alembic check` doesn't compare `CHECK` constraints (see *Known gaps*). No bypass means even a one-line docs fix goes through a PR.
- **Soundbite:** "Every PR runs lint, a migration drift check and the real test suite against the same Postgres I use locally, and `main` can't merge a red build. CI holds no AWS credentials, because the Aurora test is deliberately run by hand."

## 15. Workflow Definitions: immutable versions

See [ADR 0002](docs/adr/0002-immutable-workflow-definition-versions.md). Status: **done**, built in three PRs: tables, create and read; new versions; disable and enable.

```text
workflow_definitions                       identity: what stays the same across edits
  definition_id         UUID PK            generated in the service (§7)
  name                  VARCHAR(100)       UNIQUE; renamed in place, not versioned
  is_enabled            BOOLEAN            DEFAULT true; false = Disabled
  created_at            TIMESTAMPTZ        DEFAULT now()

workflow_definition_versions               content: never updated after insert
  version_id            UUID PK            what a Workflow Run will reference
  definition_id         UUID FK            ON DELETE RESTRICT
  version_number        INTEGER            UNIQUE (definition_id, version_number), which also indexes the FK
  description           TEXT               1–2,000 characters
  confidence_threshold  NUMERIC(3,2)       CHECK (confidence_threshold > 0 AND confidence_threshold <= 1)
  steps                 JSONB              1–20 of {name, instructions}
  required_inputs       JSONB              0–20 of {key, description, type}
  sample_requests       JSONB              1–5 strings
  created_at            TIMESTAMPTZ        DEFAULT now()
```

```text
POST /api/workflow-definitions                     create the definition and version 1 in one transaction
GET  /api/workflow-definitions                     list, each with its current version, paginated, Disabled included
GET  /api/workflow-definitions/{id}                the definition with its current version
PATCH /api/workflow-definitions/{id}               rename; 409 if the name is taken (as on create)
GET  /api/workflow-definitions/{id}/versions/{n}   one specific version, for a Workflow Run's history
POST /api/workflow-definitions/{id}/versions       publish a new version; the body names its base_version
POST /api/workflow-definitions/{id}/disable        set is_enabled to false; a repeat succeeds
POST /api/workflow-definitions/{id}/enable         set is_enabled to true; a repeat succeeds
```

- **Decision:** an Admin never edits a Workflow Definition in place. Every change, a typo fix included, publishes a new Workflow Definition Version, and a Workflow Run references the exact version it started from. Identity (`name`, enabled or not) lives in one table and content in another.
- **Why:**
  - A Run that is on step 3 keeps following the steps it started with, even if an Admin deletes step 2 meanwhile.
  - History comes for free: "which threshold let this Ticket match six months ago?" is a foreign key away.
  - A Triage worker reads a version that can't change under it, so it never matches against a half-edited definition.
  - No row is ever updated, so content needs no locking and the ORM's blind spot for in-place JSON changes doesn't matter.
- **Alternatives:**
  - Edit in place and snapshot the steps and threshold onto each Run: one simple table, but every Run duplicates the content, and definitions that never got a Run keep no history.
  - Edit in place with no snapshot: simplest, but running work silently changes and history is lost.
  - One table keyed by `(definition_id, version)`: no join, but identity columns repeat on every row and a Run's foreign key needs both columns.
- **Tradeoffs:** two tables, and "current version" needs a join. A rename isn't versioned, so a Run's history shows today's name. Versions accumulate forever, which is fine at Admin editing speed.
- **Soundbite:** "Workflow Definitions are append-only. Every edit is a new immutable version and a Workflow Run pins the one it started on, so running work never changes under it and I keep a full audit trail."

### Current version: the highest number, no pointer

- **Decision:** the current version is the one with the highest `version_number`. Rolling back means publishing an old version's content as a new version.
- **Why:** nothing can drift. A `current_version_id` pointer would be a second fact that must agree with the versions table.
- **Alternatives:** a `current_version_id` column on `workflow_definitions` (rollback is one update, but it's a circular foreign key and it can point anywhere).
- **Tradeoffs:** a rollback adds a version instead of moving a pointer, which also keeps the rollback itself in the history.

### Publishing a version: `base_version` and a 409

- **Decision:** `POST /{id}/versions` takes the full content plus `base_version`, the version the Admin edited. If it isn't the current version, the response is 409. If two Admins publish from v3 at the same moment, both try to insert v4. `UNIQUE (definition_id, version_number)` rejects the second one, which also becomes a 409.
- **How:** the service compares `base_version` with the current version and inserts `base_version + 1`, never `max + 1` from the read. The read and the insert aren't atomic, and they don't need to be: the inserted number doesn't depend on the read. The check rejects a `base_version` that is stale and one that is ahead of current, which the constraint alone would miss (`base_version` 9 would insert v10 and leave a gap). The constraint catches a publish that races past the check.
- **Why:** the Admin who loses a race finds out instead of silently overwriting the other's edit. The route says what really happens, which is creating a version, not replacing a resource.
- **Alternatives:**
  - `PUT /{id}` with an `If-Match` ETag (the standard HTTP form of optimistic concurrency, but `PUT` reads as overwriting something that is actually immutable).
  - A `SELECT ... FOR UPDATE` lock on the definition row, which serialises publishers so the check and the insert act as one step. Every publish then waits on the lock to guard against a collision that almost never happens, and the constraint is still needed as the safety net.
- **Tradeoffs:** a client must always send the full content, even to fix one word.
- **Soundbite:** "Edits use optimistic concurrency. The client names the version it edited, and a unique constraint makes the database the referee if two Admins publish at once."

### Disabling instead of deleting

- **Decision:** there is no `DELETE`. `POST /disable` sets `is_enabled` to false and `POST /enable` sets it to true, each as a plain write that also succeeds on a repeat (as with cancelling, §11). Triage skips a Disabled definition, its active Runs finish on their versions, and its name stays reserved. Admins can publish versions while it's Disabled, so they can pause it, fix it and enable it again. Foreign keys are `ON DELETE RESTRICT`.
- **Why:**
  - Runs reference versions, so a deleted definition would break their history.
  - A temporary pause and a permanent retirement behave the same for Triage. One reversible state covers both: a retired definition is one that stays Disabled.
  - A boolean is enough: it's a two-state toggle, and nothing needs to know when it last flipped.
  - No compare-and-set, unlike cancelling. Cancel needs `WHERE status IN (...)` because some statuses forbid it and must return 409 atomically. Here every starting state is allowed, so there is no 409 to protect, and concurrent disable and enable resolve as last commit wins, which is right for a toggle. Setting an unchanged value also sends no `UPDATE`.
  - The Triage worker checks `is_enabled` in the same transaction that creates the Run, so disabling during Triage's LLM call wins.
- **Alternatives:**
  - A permanent Retired state: guards against reactivating by accident, but a pause then needs a second state.
  - Paused plus Retired: clearer intent, but two states that behave identically and a transition table to defend.
  - Hard delete when there are no Runs: tidier, but one verb with two outcomes.
  - A nullable `disabled_at` timestamp: also says when, but re-enabling erases it, so it can't answer "was this disabled last Tuesday?" either.
  - A `WorkflowDefinitionStatus` enum like Ticket Status: an explicit status and room for a third state such as a Draft, but with two values it's a boolean with extra ceremony, and adding a value later needs a `CHECK` migration anyway.
- **Tradeoffs:** Disabled definitions stay in the list forever. Nothing records when or how often a definition was disabled; that needs an event log if it ever matters. The name is **Disabled**, not Paused, because "pausing" a definition sounds as if its active Runs pause too, and they don't.
- **Soundbite:** "Nothing that a Run can reference is ever deleted. Admins disable a Workflow Definition, which only stops Triage from selecting it, and it's reversible because a pause and a retirement look the same to Triage."

### Storage: JSONB for the lists, TEXT for prose

- **Decision:** Steps, Required Inputs and Sample Requests are `JSONB` columns on the version row, validated by Pydantic at the API. `name` is `VARCHAR(100)`, while `description` and Step instructions are plain-text `TEXT`. Every length limit is a Pydantic `max_length`. A Required Input has a `key` (`^[a-z][a-z0-9_]{0,49}$`, unique within the version), a `description` (1–500 characters), and a `type` of `string`, `number`, `boolean` or `date`. Every Required Input is required, so there is no optional flag.
- **Why:**
  - A version is immutable and always read whole, so it's one document. That means one insert and one select, and the array order is the Step order.
  - Child tables pay off for updating or querying individual elements. Versions are never updated, and no planned feature queries inside the lists. If one does, `required_inputs @> '[{"key": "budget"}]'` with a GIN index can answer it.
  - `JSONB` over `JSON`: it's parsed once on write and can be indexed, while `JSON` re-parses text on every read.
  - In Postgres, `TEXT` and `VARCHAR(n)` have the same storage and speed. Long values are compressed or moved out of line automatically (TOAST). The limits exist mainly because `description` and Sample Requests go into every Triage prompt, so their length is LLM cost.
  - A snake_case `key` and a closed set of types can go straight into a tool schema for the Intake Agent (§16).
- **Alternatives:** child tables for Steps, Required Inputs and Sample Requests (the database enforces the structure, but it's three more tables and every edit copies all their rows); a full JSON Schema per definition for Required Inputs (standard and expressive, but it needs a validator dependency, and Admins could write schemas nothing else can handle).
- **Tradeoffs:** the database can't enforce the inner structure, only coarse checks such as `jsonb_typeof` and `jsonb_array_length`. Every write must go through the validated API.
- **Soundbite:** "Each version is an immutable document, so the lists are JSONB, validated by Pydantic at the edge. I'd move to child tables if I ever needed to update or query individual elements."

### Confidence Threshold: `NUMERIC(3,2)`, no default

- **Decision:** `NUMERIC(3,2)` with `CHECK (> 0 AND <= 1)` and no default. Triage selects a definition when Match Confidence `>=` the threshold.
- **Why:** 0.80 is stored exactly, so the comparison at the boundary is exact. A threshold of 0 would match everything. With no default, each Admin has to choose a threshold based on how consequential the workflow is.
- **Alternatives:** `DOUBLE PRECISION` (a plain `float` everywhere, but 0.80 is only approximate, so the boundary depends on floating-point behaviour).
- **Tradeoffs:** Python sees `Decimal`, which Pydantic v2 writes to JSON as a string unless the response model says otherwise.
- **Where Match Confidence comes from (decided):** the model reports it as a number from 0.00 to 1.00 for each candidate definition, and Triage compares it with the threshold in code, never in the prompt. Self-reported confidence is poorly calibrated, which is accepted for now (see *Known gaps*).

### Sample Requests: dynamic context injection

- **Decision:** Triage reads a definition's `name`, `description` and Sample Requests, but not its Steps or Required Inputs. When Triage runs, the current version of every enabled definition is assembled into the prompt, with 1–5 Sample Requests each (few-shot prompting). Ticket text sits in clearly delimited data, never in the instructions.
- **Why:** Sample Requests show the model how Users actually phrase a need, which a description alone doesn't. Assembling them at runtime means an Admin's edit takes effect on the next Ticket without a deploy.
- **Alternatives:** description only (less to maintain, but matching has only the Admin's wording to go on); choosing the Sample Requests closest to each Ticket with embeddings (scales better, but needs pgvector, an embedding model and a re-embed on every edit).
- **Tradeoffs:** the prompt grows with every definition. The planned fix is the two-stage match in §12: an embedding shortlist first, then a prompt with only the shortlisted definitions and their Sample Requests. Ticket text is the untrusted input, so delimiting it is the first defence against prompt injection.
- **Soundbite:** "Admins give each workflow a few Sample Requests, and Triage injects them into its prompt at runtime as few-shot examples, so improving matching is a data change, not a deploy."

## 16. Required Inputs: collected after Triage

Status: **planned**. Input submission and validation come with the Workflow Run milestone (§17); the Intake Agent turn that collects them comes with Conversation.

```text
Triage selects definition ─▶ Ticket TRIAGED + Workflow Run waiting for inputs (one transaction)
        │ after commit
        ▼
   event ─▶ Intake Agent turn: Required Inputs from the Run's version + Conversation history
                ├─ value in Ticket.message      ─▶ accept
                ├─ value elsewhere in history   ─▶ confirm with the User
                └─ value missing                ─▶ ask the User
            submit tool ─▶ service validates types and completeness ─▶ Run starts
```

- **Decision:** matching is about intent only. Triage creates the Run even when Required Inputs are missing, the Ticket becomes TRIAGED, and the Run waits. The Intake Agent learns what is missing through Run → Workflow Definition Version → `required_inputs`, which the service adds to its prompt on every turn. It submits values through a tool, and the service validates them. Values found in `Ticket.message` are accepted, and values found elsewhere in the Conversation are confirmed with the User. When Triage finishes, the worker writes a `ticket.triaged` outbox event in the same transaction as TRIAGED (§18), and its delivery starts an Intake Agent turn with no User Message. That turn writes the question into the Conversation, and the client sees it by polling at first.
- **Why:**
  - The Intake Agent can't collect inputs up front, because it doesn't know the workflow until Triage finishes.
  - Keeping inputs on the Run leaves the Ticket lifecycle (§11) unchanged.
  - A Conversation can produce several Tickets. "Get me a laptop and a monitor, budget $2000" puts a value into the history that may belong to one Ticket, both or neither, so copying it into every Run without asking could be wrong without anyone noticing.
  - §12 makes the Intake Agent one LLM call per User turn, so nothing is running for a worker to ask. Without an agent-initiated turn, a Run would wait until the User happened to write again.
  - As in §12, the LLM decides what to submit and the service decides whether it's valid.
- **Alternatives:** a new Ticket Status that holds the Ticket until its inputs are complete (no half-ready Runs, but a status and a loop in the Ticket lifecycle); accepting every value found in the history (fewer questions, but the laptop and monitor mistake goes through); waiting for the User's next message (nothing to build, but Runs get stuck).
- **Tradeoffs:** a Run can wait forever if the User never answers, and a timeout is still to be designed. Agent-initiated turns need an event consumer and a client that polls or streams. `tickets` needs a `conversation_id`.
- **Soundbite:** "Triage only decides what the User wants. The Workflow Run then collects what it needs: the Intake Agent reuses what the User already said, confirms anything it took from elsewhere in the Conversation, and asks only for what's missing."

## 17. Workflow Runs: one per Ticket, pinned to a version

Status: **done**, built in three PRs: the table, `create_workflow_run` and the read routes; Required Input submission; cancelling a TRIAGED Ticket with its Run, and the 409 for deleting a Ticket that has one. Carrying out Steps is a later milestone. Builds on [ADR 0002](docs/adr/0002-immutable-workflow-definition-versions.md).

```text
workflow_runs
  run_id      UUID PK        generated in the service (§7)
  ticket_id   UUID FK        UNIQUE: one Run per Ticket, ever, and its index serves the FK; ON DELETE RESTRICT
  version_id  UUID FK        → workflow_definition_versions; indexed; ON DELETE RESTRICT
  status      VARCHAR(20)    Workflow Run Status, CHECK constraint (as §11)
  inputs      JSONB          {key: value} of supplied Required Inputs; DEFAULT '{}'
  created_at  TIMESTAMPTZ    DEFAULT now()
```

```text
created by Triage ─┬─ has Required Inputs ─▶ AWAITING_INPUTS ──all supplied──▶ READY
                   └─ has none ─────────────────────────────────────────────▶ READY
READY ──▶ RUNNING ──▶ COMPLETED | FAILED                     (execution: a later milestone)
CANCELLED: from AWAITING_INPUTS, READY or RUNNING, only by cancelling the Ticket
```

```text
GET  /api/workflow-runs/{run_id}             one Run; 404 if missing
GET  /api/tickets/{ticket_id}/workflow-run   a Ticket's Run; 404 if the Ticket or its Run is missing
POST /api/workflow-runs/{run_id}/inputs      submit Required Inputs; 404 / 409 / 422
```

- **Decision:** this milestone builds the Run as a record: the table, a `create_workflow_run` service function for Triage, the read routes and input submission. Carrying out Steps is a later milestone. There is no public `POST /workflow-runs`, because only Triage creates Runs.
- **Why:**
  - Triage needs somewhere to write its result before it can be built, and §16's input collection needs a Run to collect into.
  - Who carries out the Steps (an LLM, a person, both) is still open. Deciding it now would be guessing.
- **Alternatives:** design execution now too (the status set would be final, but the milestone grows and rests on guesses); wait for the Conversation milestone to add input submission (smaller, but nothing could reach READY, so the lifecycle would go untested).
- **Tradeoffs:** RUNNING, COMPLETED and FAILED exist before anything can reach them.
- **Soundbite:** "A Workflow Run pins the exact Definition Version Triage selected, one per Ticket. I built the record and its input collection first, and left execution until I know who carries out the Steps."

### Relationships: version only, one Run per Ticket

- **Decision:** the Run references `version_id`, not `definition_id`; the definition is one join away. `UNIQUE (ticket_id)` allows one Run per Ticket, ever. Both foreign keys are `ON DELETE RESTRICT`. Deleting a Ticket that has a Run returns 409: `remove_ticket` flushes the delete, catches the `IntegrityError` only when its constraint is `fk_workflow_runs_ticket_id_tickets`, and raises `ValueError`, as the duplicate-name check does (§15). Without the flush, the violation would surface at commit, after the handler returned, as a 500. The User cancels such a Ticket instead.
- **Why:**
  - A stored `definition_id` would be a second copy of the version's parent, free to disagree with it.
  - TRIAGED is the end of the Ticket lifecycle (§11), and nothing re-triages a Ticket, so a second Run can't happen. The database enforces it instead of the code assuming it.
  - Letting the constraint decide is race-free. A check-then-delete would miss a Run that Triage commits in between, and that delete would then fail with a 500.
  - Nothing a Run references is deleted, the same rule that makes Workflow Definitions Disabled rather than deleted.
- **Alternatives:** also store `definition_id` (no join for "Runs of definition X", but it can drift); a partial unique index over active Runs only (allows re-runs later, but needs "active" defined and nothing needs re-runs); `ON DELETE CASCADE` (simple, but work in progress disappears without a trace); checking for a Run before deleting (plainer code, but the race above).
- **Tradeoffs:** "Runs of definition X" needs a join. A triaged Ticket can never be deleted. Re-triage would mean replacing `UNIQUE` with a partial index, which is an easy migration. The `IntegrityError` catch must match only this constraint, so another integrity failure doesn't become a misleading 409.

### No Match Confidence on the Run

- **Decision:** the Run doesn't store the Match Confidence that selected it.
- **Why:** a Run is selected under one rule, Match Confidence `>=` the version's Confidence Threshold, and the threshold is already kept on the version. What the Run needs to do its work is the version and the inputs. Why Triage chose it is Triage's concern.
- **Alternatives:** a `match_confidence NUMERIC(3,2)` column (keeps the exact score, for debugging Triage).
- **Tradeoffs:** the scores live in `triage_results` instead (§18), one row per Triage Provider, so the Run stays about the work and Triage keeps its own record.

### Workflow Run Status: the full set up front

- **Decision:** six statuses (see `GLOSSARY.md`), stored like Ticket Status (§11): `VARCHAR(20)` with a `CHECK` constraint, set only by the system. A Run whose version has no Required Inputs starts at READY.
- **Why:** the same as §11. Each status is a place a Run can wait or get stuck. Defining the execution statuses now saves a hand-written `CHECK` migration next milestone, since autogenerate doesn't detect `CHECK` changes.
- **Alternatives:** only the statuses reachable today (AWAITING_INPUTS, READY, CANCELLED): the constraint covers only reachable values, but the next milestone must migrate it.
- **Tradeoffs:** three values nothing can reach yet. Only `created_at` is stored; `started_at` and `completed_at` wait until execution writes and something reads them.

### Creating a Run: one transaction with TRIAGED

- **Decision:** `workflow_run_service.create_workflow_run(session, ticket_id, version_id)` runs in the caller's transaction (§5):
  1. Compare-and-set the Ticket from TRIAGING to TRIAGED. If no row matches (the Ticket was cancelled, say), raise `ValueError` and insert nothing.
  2. Load the version and read its definition's `is_enabled` with a plain `SELECT`. If it's Disabled, raise `ValueError`; the transaction rolls back, and the Ticket stays TRIAGING for Triage to try again.
  3. Insert the Run with status READY or AWAITING_INPUTS.

  Until Triage exists, tests call the service directly in the rollback session, after moving the Ticket to TRIAGING with `modify_ticket_status`.
- **Why:**
  - Both writes or neither: a TRIAGED Ticket without a Run, or a Run for a cancelled Ticket, can't exist (§11, *What workers must do*).
  - `is_enabled` needs no lock. If a disable commits before the read, the read sees it. If it commits after, the outcome is the same as disabling just after the Run was created, which is allowed, because Disabled only stops new selections.
  - Ticket first, then Run, is the same order cancelling uses, so the two can't deadlock.
- **Alternatives:** `SELECT ... FOR SHARE` on the definition (a disable waits for the Run's commit, but it prevents no anomaly and only makes Admins wait); a test-only HTTP route that creates Runs (tests stay on `TestClient`, but the app ships an endpoint only tests need).
- **Tradeoffs:** `create_workflow_run` is tested without its real caller until Triage lands.

### Cancelling through the Ticket

- **Decision:** `TRIAGED` joins the Ticket's cancellable statuses. `cancel_ticket` runs in one transaction:
  1. Compare-and-set the Ticket to CANCELLED.
  2. Look up its Run by `ticket_id`. If there is none, the cancel is done.
  3. Compare-and-set the Run to CANCELLED from AWAITING_INPUTS, READY, RUNNING or CANCELLED. If the Run is COMPLETED or FAILED, this raises, the whole transaction rolls back, the Ticket stays TRIAGED, and the response is 409.

  There is no Run cancel endpoint.
- **Why:**
  - Finished work can't be withdrawn, and a CANCELLED Ticket pointing at COMPLETED work would contradict itself. One command means one place for the rules.
  - The Ticket's compare-and-set returns the row after the update, so it can't say whether the Ticket *was* TRIAGED. Looking the Run up afterwards answers that without a read-then-write race.
  - The lookup can't miss a Run that Triage is creating. Step 1 holds the Ticket's row lock, and Triage must lock the Ticket before it inserts a Run. If Triage commits first, the cancel waits, sees TRIAGED and finds the Run; if the cancel commits first, Triage matches no row and creates nothing.
  - Locks are always taken Ticket first, then Run, by Triage and by cancel alike, so the two can't deadlock. Input submission locks only the Run.
  - CANCELLED is a cancellable Run status for the same reason it is for Tickets: a retried cancel must succeed (§11).
- **Alternatives:** always cancel the Ticket and leave a finished Run alone (cancel never fails, but the two disagree); also `POST /workflow-runs/{id}/cancel` (two entry points to keep in step, and should the Ticket follow?); reading the Ticket's status before updating it (says directly whether a Run exists, but it's the check-then-update race again).
- **Tradeoffs:** every cancel pays for one Run lookup, even for a Ticket that was never triaged. RUNNING is cancellable before anything runs, so the execution milestone must check the Run's status at each Step.

### Submitting Required Inputs: a JSONB merge in a compare-and-set

- **Decision:**
  - The body is `{"inputs": {key: value}}`. Submissions can be partial, and a key can be overwritten while the Run is AWAITING_INPUTS. Once it's READY, every submission returns 409.
  - The service loads the version and validates the values with a Pydantic `TypeAdapter` over a `TypedDict` built at runtime from its `required_inputs` (`total=False`, `strict=True`, `extra="forbid"`). An unknown key, `null` or a wrong type returns 422, and so does an empty object, which the request model rejects. There is no coercion: `"1500"` is not a number.
  - Then one statement: `UPDATE workflow_runs SET inputs = inputs || :new WHERE run_id = :id AND status = 'AWAITING_INPUTS' RETURNING ...`. If the merged inputs cover every key, a second compare-and-set in the same transaction moves the Run to READY.
- **Why:**
  - Two concurrent half-submissions can't lose each other's values. Under `READ COMMITTED`, the second `UPDATE` waits for the first to commit, then re-evaluates `inputs || :new` against the committed row. The row stays locked until commit, so the completeness check sees every value.
  - Overwriting lets the User correct a value ("actually, $1500"). Freezing at READY means execution never sees values change under it.
  - A runtime validator gives a `ValidationError` and FastAPI's usual 422 format, and `strict=True` handles the bool trap: `isinstance(True, int)` is `True` in Python, but strict mode rejects `true` for a number.
  - A `TypedDict`, not `create_model`: a model's fields share a namespace with `BaseModel`, and keys the key pattern allows clash with it (`model_dump` fails to build, `model_config` is read as configuration, `json` shadows a method). A `TypedDict` has no such names, and since its values aren't `| None`, `null` is rejected without extra work.
- **Errors:** `ValueError` still means 409 (§11). `pydantic.ValidationError` is a subclass of `ValueError`, so the router must catch `ValidationError` → 422 **before** `ValueError` → 409, with a comment saying why.
- **Alternatives:** `SELECT ... FOR UPDATE`, merge in Python, write back (plain ORM, but breaks "every transition is a compare-and-set"); write-once keys (guard against agent mistakes, but the User can't fix a wrong value); a `workflow_run_inputs` child table (easy per-value updates and provenance, but one more table, as §15 argued); coercing types (friendlier, but the service guesses on the LLM's behalf); hand-written checks raising a custom `InvalidInputsError` (no `except` ordering to remember, but one more class and a home-made error format); a `ConflictError` replacing `ValueError` for 409 everywhere (names the meaning and removes the ordering trap, but changes four existing call sites for one new case).
- **Implementation notes:**
  - Validate in JSON mode (`model_validate_json`). Strict Python-mode validation rejects `"2026-11-07"` for a `date`; JSON mode accepts it.
  - A `string` field needs `min_length=1`.
  - A `number` comes back as a float (`3` → `3.0`); store `model_dump(mode="json", exclude_unset=True)`.
- **Tradeoffs:** the ordering of `except` clauses is a silent dependency. The database can't check the values; every write must go through the service.

### Responses: values computed at read time

- **Decision:** `WorkflowRunItem` returns the stored columns plus `definition_id` and `version_number` (from a join) and `missing_inputs` (the version's keys not yet in `inputs`). None of them is stored.
- **Why:** the only route that reads a version takes a definition ID and a version number, so a client holding only `version_id` couldn't reach it. The Intake Agent needs `missing_inputs` on every turn (§16), and computing it from immutable data can't drift.
- **Alternatives:** stored columns only, plus a `GET /workflow-definition-versions/{version_id}` route (a pure response, but a second way to read a version, and every client works out what's missing); `GET /workflow-runs?ticket_id=` instead of the nested route (a filter that returns a list of at most one).
- **Where it's built:** `get_missing_inputs(run, version)` lives in `workflow_run_service.py`, in the version's key order, because input submission needs the same check. The read services return `(run, version)`, and the router's `_to_item` builds the item, as the Workflow Definition router does. `GET /tickets/{ticket_id}/workflow-run` lives in `ticket_router`, which owns the URL, and calls the Workflow Run service. A missing Ticket and a Ticket without a Run give the same 404.
- **Tradeoffs:** every read loads the version for the join and for `missing_inputs`. The router calls a second service function to build the item.

## 18. Triage: outbox, SQS and consensus across providers

Status: **designed**, to be built before Conversation (§19), in four PRs that each leave the app runnable (`POST /api/tickets` keeps working until §19 removes it):

1. **Outbox:** remove CREATED with a hand-written `CHECK` migration, so `create_ticket` inserts QUEUED plus an outbox row; the `outbox` table, the relay, ElasticMQ in `docker-compose.yml` and CI, and an `sqs.md` rules file.
2. **Triage decision:** `triage_results`, `claimed_at` and `triage_attempts`; the `TriageProvider` Protocol and a fake; the Triage service (claim, consensus, finishing with the fencing check, calling `create_workflow_run`), tested by calling the service directly.
3. **Workers and providers:** the triage worker loop, the DLQ consumer, and the Anthropic and Gemini adapters, with their dependencies, rules files and env vars documented.
4. **AWS, with approval for each change:** the queues, the DLQ, the IAM policy, and one test marked `aws`.

Decides how a Ticket gets from the API to a Triage worker and back, and how the worker decides. See [ADR 0003](docs/adr/0003-consensus-triage.md).

```text
Intake Agent tool ─▶ tx: insert Ticket (QUEUED) + outbox row ticket.queued
                                    │
relay process ─── polls outbox ─────┘──▶ SQS triage queue (standard) ──3 failed receives──▶ DLQ ─▶ Ticket FAILED
                                                   │
triage worker (separate process, long polling) ◀───┘
  tx1: claim QUEUED → TRIAGING, set claimed_at          commit
       every Triage Provider scores the Ticket            no transaction open
  tx2: insert triage_results, then
       ├─ all agree ─▶ TRIAGING → TRIAGED + Workflow Run + outbox ticket.triaged
       └─ otherwise ─▶ TRIAGING → UNMATCHED              + outbox ticket.unmatched
       commit, then delete the SQS message
```

```text
outbox
  event_id      UUID PK
  event_type    VARCHAR(50)    ticket.queued, ticket.triaged, ticket.unmatched
  payload       JSONB          {"ticket_id": ...}
  created_at    TIMESTAMPTZ    DEFAULT now()
  published_at  TIMESTAMPTZ    NULL until the relay has sent it; partial index WHERE published_at IS NULL

triage_results                 one row per Triage Provider per attempt
  result_id         UUID PK
  ticket_id         UUID FK    indexed; ON DELETE RESTRICT
  provider          VARCHAR    e.g. anthropic, gemini
  model             VARCHAR    the exact model ID
  definition_id     UUID FK    NULL when the provider selected nothing
  match_confidence  NUMERIC(3,2) NULL, as the threshold
  created_at        TIMESTAMPTZ

tickets.claimed_at       TIMESTAMPTZ NULL      set by each claim
tickets.triage_attempts  INTEGER DEFAULT 0     incremented in tx2; at most 3
```

### The transactional outbox

- **Decision:** nothing writes to Postgres and SQS in one step. A Ticket and its `ticket.queued` outbox row are inserted in one transaction. A relay process loops: `SELECT ... FROM outbox WHERE published_at IS NULL ORDER BY created_at LIMIT 10 FOR UPDATE SKIP LOCKED`, sends each row to the queue its `event_type` maps to, sets `published_at`, and commits. The outbox is generic: the worker writes `ticket.triaged` and `ticket.unmatched` the same way, which start the Intake Agent turns of §16 and §19.
- **Why:**
  - Commit-then-send loses the message if the process dies in between; send-then-commit publishes a Ticket that may roll back. With one transaction, a saved Ticket always has an outbox row, and the relay eventually sends it.
  - A relay that crashes after sending but before committing sends the row again. That's a duplicate, which the worker's compare-and-set claim makes harmless: exactly-once across two systems is impossible, so the design is at-least-once delivery with an idempotent consumer.
  - `SKIP LOCKED` lets two relays run without sending the same row.
  - It removes CREATED (§11): a Ticket's publishing is guaranteed, so there's no "saved but not published" state to recover from.
- **Alternatives:** commit, publish, then CREATED → QUEUED with a sweeper (no extra table or process, but the worker-before-update race and a sweeper to run); Postgres as the queue with `SKIP LOCKED` workers (no dual write at all and no AWS, but no SQS redelivery, DLQ or visibility timeouts, which then have to be built by hand).
- **Tradeoffs:** one more table and one more process. Delivery is delayed by the relay's polling interval. Published rows accumulate and need pruning eventually.
- **Soundbite:** "I never write to two systems in one step. The Ticket and its outbox event commit together, a relay publishes to SQS, and a duplicate from a relay crash is harmless because the worker's claim is a compare-and-set."

### SQS: a standard queue, a DLQ, and stale claims

- **Decision:** a standard queue (not FIFO), whose message body is only `{"ticket_id": ...}`. The visibility timeout is about 60 s. A DLQ with `maxReceiveCount = 3` catches Tickets that keep failing, and a DLQ consumer compare-and-sets them to FAILED. The worker runs as its own long-polling process, not inside Uvicorn.
- **Claiming:** `UPDATE tickets SET status = 'TRIAGING', claimed_at = now() WHERE ticket_id = :id AND (status = 'QUEUED' OR (status = 'TRIAGING' AND claimed_at < now() - interval '90 seconds')) RETURNING claimed_at`. The interval is longer than the visibility timeout, so a crashed worker's Ticket is taken over by the redelivery instead of hanging in TRIAGING.
- **Finishing:** tx2 compare-and-sets `WHERE status = 'TRIAGING' AND claimed_at = :my_claimed_at`. `claimed_at` is a fencing token: a slow worker whose claim was taken over matches no row, so two workers can never both finish the same Ticket.
- **Why:**
  - Duplicate delivery is already handled by the claim, and order doesn't matter, so FIFO's limits and cost buy nothing.
  - A message with only the ID can't go stale; the worker reads the current Ticket and definitions from Postgres.
  - "Retries used up" in §11 becomes SQS's own receive count, with no retry counter of our own.
  - No transaction is open during LLM calls, so a cancel never waits on a provider (as §19's turns).
- **Errors:** a provider error, malformed output, a `definition_id` that wasn't a candidate or a Match Confidence outside 0–1 is an exception. The worker validates provider output with a Pydantic model. The message isn't deleted, SQS redelivers it, and the third failure sends it to the DLQ.
- **Alternatives:** a `retries` column and our own backoff (works with any queue, but duplicates what SQS does); a separate timeout sweeper for TRIAGING (one more process, where redelivery already triggers the check).
- **Tradeoffs:** tuning: the visibility timeout must cover every provider's latency, and the stale-claim interval must stay above it. A Ticket that fails three times needs a person to look at it.

### Consensus across Triage Providers

- **Decision:** each Triage Provider scores the Ticket independently against the current version of every enabled Workflow Definition and selects its best qualifying definition: the highest Match Confidence that meets that definition's Confidence Threshold, or none. A Workflow Run is created only if every provider selected the same definition. Otherwise the Ticket is UNMATCHED. Every provider's selection is stored in `triage_results`, whatever the outcome.
- **How:** the providers are called in parallel from a `ThreadPoolExecutor` (the worker stays synchronous), each with a timeout of about 20 s, so the slowest one sets the latency and both fit inside the visibility timeout. A timeout is a provider error. If no definition is enabled, no provider is called, nothing is stored and the Ticket is UNMATCHED. The active providers come from `TRIAGE_PROVIDERS` (e.g. `anthropic,gemini`), so one can run alone locally. Models: `claude-haiku-5-5` and Gemini Flash, two small, fast models, which keeps the comparison fair.
- **Why:** a wrong Run starts work nobody asked for, while an UNMATCHED Ticket costs one clarifying question. Requiring agreement trades recall for precision, which is the same reason Confidence Thresholds exist. The stored results are also the comparison between providers.
- **Alternatives:** one primary provider, plus offline evaluation on a labelled set (cheaper and faster, but one model's mistakes go straight to Runs); shadow mode (others score but never decide); a separate `DISPUTED` status for disagreement (more precise, but the User sees the same clarifying questions as for UNMATCHED).
- **Tradeoffs:** cost is the sum of the providers, latency is the slowest, and availability is the product: if one provider is down, Triage fails and retries. Gemini's free-tier rate limit caps throughput. "UNMATCHED" now covers both "nothing qualified" and "providers disagreed", which only `triage_results` tells apart.
- **Soundbite:** "Two different models must independently pick the same workflow above its threshold before any work starts. I trade some recall for precision, and every provider's answer is stored, so the same data tells me how the models compare."

### Triage Providers behind a Protocol

- **Decision:** a `TriageProvider` `typing.Protocol` with `score(request, definitions) -> list[MatchResult]`, implemented once per provider with that provider's SDK (`anthropic`, `google-genai`), each using its own structured output. Thresholds and consensus are plain code in the Triage service, never in a prompt. Tests use a fake provider, so `pytest` never calls an LLM.
- **Why:** the service doesn't know which SDK it's talking to, and each adapter is a short translation you can read in one pass. Structured output is where providers differ most, so that's where the code should be explicit.
- **Alternatives:** LiteLLM (one dependency for every provider, but a large dependency tree and an abstraction that leaks around structured output).
- **Tradeoffs:** two SDKs to keep up to date, and a third provider means a third adapter.

### Local testing

- **Decision:** ElasticMQ, an SQS-compatible server, runs in `docker-compose.yml` next to Postgres and in CI. An `SQS_ENDPOINT_URL` env var points boto3 at it, and tests set it. One deliberate test against real SQS is marked `aws`, like `aurora`.
- **Alternatives:** moto (in-process, no container, but it mocks boto3 itself, so less of the real protocol is tested).
- **AWS setup still needed (with approval):** the queue, the DLQ, and an IAM policy for the app's `sqs:*Message` actions on them; the `daniel` IAM user currently has no SQS permissions.

## 19. Conversation and the Intake Agent turn

Status: **designed**, to be built after Triage (§18).

```text
conversations                       messages
  conversation_id  UUID PK            message_id       UUID PK
  user_id          VARCHAR            conversation_id  UUID FK, index (conversation_id, created_at)
  turn_started_at  TIMESTAMPTZ NULL   author           VARCHAR(20)  USER | INTAKE_AGENT, CHECK constraint
  created_at       TIMESTAMPTZ        content          TEXT
                                      created_at       TIMESTAMPTZ

tickets: + conversation_id UUID FK NOT NULL (indexed); message → request; − user_id
```

```text
POST /api/conversations                     create; body {user_id}
GET  /api/conversations/{id}                the Conversation and its Tickets
GET  /api/conversations/{id}/messages       Messages, oldest first, paginated; clients poll it
POST /api/conversations/{id}/messages       a User Message; runs a turn; 201 with the Intake Agent's reply
POST /api/tickets and PATCH /api/tickets/{id} are removed: Tickets change only through the Intake Agent.
```

- **Decision:**
  - Every Ticket belongs to a Conversation, and only the Intake Agent creates Tickets, so `POST /api/tickets` goes away. The owner (`user_id`) lives on the Conversation only.
  - Only User and Intake Agent Messages are stored. Tool calls and their results aren't. Each turn, the service injects the Conversation's current state: its Tickets, their statuses and their Runs' `missing_inputs`.
  - A turn commits step by step, and no transaction is open during an LLM call: (1) save the User's Message, (2) each tool call in its own transaction, (3) save the Intake Agent's reply. If an LLM call fails mid-turn, effects already committed stay, and the User gets a fixed error reply.
  - Messages are read from Postgres only, with no application cache. Each turn sends the last 20 Messages plus the injected state, using `claude-sonnet-5-5`.
  - **Clarifying an UNMATCHED Ticket:** the tool `clarify_ticket(ticket_id, request)` takes the whole request rewritten as one coherent statement. In one transaction the service compare-and-sets UNMATCHED → QUEUED, replaces `request` and writes a `ticket.queued` outbox row. The old wording stays in the Messages and the old scores in `triage_results`. After 3 Triage attempts the agent tells the User no workflow fits, and the Ticket stays UNMATCHED.
  - **One turn per Conversation:** a turn reads the state once and acts on it for seconds, so two concurrent turns (a double send, or a User turn meeting an agent-initiated one) could create duplicate Tickets or ask about a Ticket just cancelled. A turn first takes a lease: `UPDATE conversations SET turn_started_at = now() WHERE conversation_id = :id AND (turn_started_at IS NULL OR turn_started_at < now() - interval '2 minutes') RETURNING turn_started_at`, and clears it in the transaction that saves the reply, `WHERE turn_started_at = :mine` (a fencing token, as `claimed_at` in §18). A User turn that loses gets 409 before its Message is saved. An agent-initiated turn that loses leaves its SQS message undeleted and runs after redelivery. A crashed turn's lease goes stale after 2 minutes, longer than five loop iterations.
  - **Agent-initiated turns:** `ticket.triaged` and `ticket.unmatched` go to a second SQS queue, `intake-events`. An intake worker consumes it and runs a turn with no User Message, which asks for missing Required Inputs or clarifying questions. Clients see new Messages by polling. The processes besides the API (relay, triage worker, intake worker) live in `app/workers/`.
- **Why:**
  - Replayed tool results would show Ticket statuses as they were, not as they are. Injected state is smaller and always current.
  - A whole-turn transaction would hold a pooled connection and row locks across seconds of LLM calls (a cancelled Ticket would block the Triage worker's claim), and a late failure would roll back the User's own Message.
  - Workers never read the Conversation, and the Intake Agent's read is one indexed query, milliseconds next to the LLM call. A cache would add infrastructure and a second copy to keep in step. The caching that pays off is LLM prompt caching of the fixed prefix, which belongs to the prompt-engineering pass.
- **Alternatives:** a session-level advisory lock per Conversation (released automatically if the connection drops, but it holds a pooled connection for the whole turn); `SELECT ... FOR UPDATE` on the Conversation (needs a transaction open across LLM calls); appending a clarification to the request instead of rewriting it (simpler, but Triage must untangle "laptop… actually a monitor"); store tool calls and replay them (the model sees its own reasoning, but stale state and a bigger prompt); one transaction per turn (all-or-nothing turns, at the costs above); a Redis or ElastiCache copy of each Conversation (faster reads that nothing needs).
- **Tradeoffs:** a failed turn can leave committed effects without a reply that mentions them; the next turn's injected state shows them. The renamed `request` column and dropped `user_id` need a migration and test updates.
- **Soundbite:** "The Conversation stores only what the User and the agent said. Every turn rebuilds the current state from the database, and nothing holds a transaction while an LLM is thinking."

---

## Known gaps

- There is no authentication, so no endpoint checks that the caller owns the Ticket. §12 requires this check for cancelling, and a client-supplied `user_id` wouldn't prove ownership. The Workflow Definition endpoints (§15) are just as open: anyone can act as an Admin.
- The cancel race has no automated test, because the rollback fixture runs on one connection. It was checked by hand with two connections and real commits against the local database.
- Concurrent Required Input submissions have no automated test either, for the same reason. Checked by hand: the second `UPDATE` waited for the first to commit, and the Run kept both values (§17).
- The test session is shared by every request in a test, so a request that fails after writing could leave a stale object in its cache: the savepoint rolls back the database, but an object refreshed by `UPDATE ... RETURNING` isn't expired with it. The override in `tests/conftest.py` expires the session after a failed request, as a fresh production session would never see the stale object. Found when a cancel that returned 409 still read back as CANCELLED.
- `UpdateTicketRequest` fields are typed without `| None` but default to `None`. This is deliberate: Pydantic doesn't validate defaults, so an omitted field is simply unset (and dropped by `exclude_unset=True`), while an explicit `null` is rejected with 422 instead of reaching a `NOT NULL` column and failing with 500. The cost is an annotation that type checkers flag.
- `alembic check` doesn't compare `CHECK` constraints, so adding a `TicketStatus` member without a migration passes it. An API test that stores the new status would fail against the old constraint, so add one with each new status.
- Match Confidence is the model's own estimate and isn't calibrated, so a 0.80 threshold doesn't mean 80% of such matches are right. Comparing providers on labelled requests is the first step towards measuring it.
- Nothing exists yet for Conversation or Triage; both are designed (§18, §19). Workflow Runs can be created, read, given Required Inputs and cancelled through their Ticket (§17).
- A Ticket has no link to its Conversation, so the Intake Agent can't read the history §16 relies on. Decided for the Conversation milestone: every Ticket belongs to a Conversation (`conversation_id NOT NULL`), only the Intake Agent creates Tickets, so `POST /api/tickets` goes away, `tickets.message` is renamed to `request`, because *Message* now means an entry in a Conversation, and `tickets.user_id` is dropped: the owner lives on the Conversation, so a copy on the Ticket could only drift.
