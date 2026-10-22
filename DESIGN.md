# Design

Interview-prep notes: what was decided, why, what else was considered, and what it costs. Terms follow [GLOSSARY.md](GLOSSARY.md).

## Overview

AI Triage Platform turns natural-language requests into structured work. A User talks to an AI agent; each distinct request becomes a Ticket; the agent triages the Ticket to a predefined Workflow Definition once its Match Confidence clears that definition's Confidence Threshold, which creates a Workflow Run. Today only the Ticket API exists: a FastAPI backend persisting to Aurora PostgreSQL.

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
      repositories/  SQL, row → dict mapping
                  │
                  ▼
           database.py ──▶ Aurora PostgreSQL Serverless v2 (us-east-2, express config, no VPC)
             today:   RDS Data API (HTTPS, boto3)
             planned: psycopg + IAM auth token, via SQLAlchemy
```

---

## 1. Layered architecture (router → service → repository)

- **Decision:** three layers. Each one calls only the layer below it.
- **Why:** HTTP concerns, business rules and persistence change for different reasons. Swapping the database client (as the IAM migration does) touches only the repository and `database.py`.
- **Alternatives:** logic inside route handlers (fine for a toy app, but it mixes HTTP and SQL); a full hexagonal / ports-and-adapters design (too much ceremony at this size).
- **Tradeoffs:** some pass-through service functions today (`get_ticket` only calls `fetch_ticket`). Accepted, because the service layer is where Triage logic will go.
- **Soundbite:** "I split routing, business logic and persistence so I could replace the data layer without touching the API. That paid off when I migrated off the Data API."

## 2. Aurora PostgreSQL Serverless v2

- **Decision:** Aurora PostgreSQL 17, Serverless v2, 0–4 ACU, auto-pause after 300 s.
- **Why:** relational data with clear relationships (Ticket → Workflow Run → Workflow Definition); scale-to-zero keeps a personal project cheap; managed backups and IAM integration.
- **Alternatives:** DynamoDB (cheap and serverless, but the data is relational and needs joins); RDS PostgreSQL on a fixed instance (simpler, but it bills 24/7).
- **Tradeoffs:** cold start of several seconds after auto-pause; AWS lock-in for the cluster itself, though the SQL stays standard Postgres.
- **Soundbite:** "My data is relational, so I chose Postgres. Serverless v2 with scale-to-zero means I only pay while I'm actually using it."

## 3. IAM auth tokens instead of the Data API

See [ADR 0001](docs/adr/0001-iam-auth-over-data-api.md). Status: **in progress**.

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

## 6. Connection pooling vs. Serverless v2 auto-pause

Status: **planned**. Numbers will be tuned during implementation.

- **Decision:** a small pool, with `pool_recycle` shorter than the 15-minute token lifetime and `pool_pre_ping` enabled.
- **Why:** pooling avoids a TLS handshake and token generation on every request. Recycling keeps reconnects regular and predictable.
- **Tradeoffs:** idle pooled connections stop Serverless v2 from auto-pausing, which costs money. Keep the pool small, and stop the app when you're not using it.
- **Soundbite:** "Pooling and scale-to-zero pull in opposite directions: open connections keep the cluster awake. I kept the pool small and short-lived."

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

- **Decision:** `PATCH /tickets/{id}` uses `model_dump(exclude_unset=True)`, and the repository only builds `SET` clauses for columns in `ALLOWED_COLUMNS`.
- **Why:** clients send only the fields they want to change. The allowlist makes the dynamic SQL safe, because column names can't be parameterised.
- **Alternatives:** PUT with a full replacement (simpler SQL, but clients must send everything).
- **Soundbite:** "Partial updates via PATCH. Column names come from an allowlist and values are parameterised, so the dynamic SQL can't be injected."

## 10. Testing: local PostgreSQL first, Aurora for what matters

Status: **planned**.

- **Decision:** run simple, fast tests against a local PostgreSQL. Run the important tests that depend on AWS (IAM auth, connectivity) against Aurora, deliberately and less often.
- **Why:** local tests are free and fast. Aurora tests catch what a local database can't, without paying for every run.
- **Tradeoffs:** small differences between local Postgres and Aurora can slip through. Mitigated by matching the major version (17) and keeping the Aurora tests for the integration edges.
- **Soundbite:** "Most tests run on a local Postgres for speed and cost. A small set runs against Aurora to cover IAM auth and the cloud-specific behaviour."

---

## Known gaps

- `DELETE /tickets/{id}` hard-deletes the row but returns `status: "DELETED"`, which is not a real Ticket Status.
- `status` is a free string. An enum (`CREATED`, `TRIAGED`) is planned.
- `UpdateTicketRequest` fields are typed `str` but default to `None` (should be `str | None`).
- `update_ticket_api` re-raises without `from e`, unlike the other handlers.
- The service layer catches `KeyError` only to re-raise it unchanged.
- Dependencies in `requirements.txt` are unpinned.
- Nothing exists yet for Conversation, Workflow Definition, Workflow Run or Triage.
