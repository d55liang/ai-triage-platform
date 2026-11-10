# AI Triage Platform
![CI](https://github.com/d55liang/ai-triage-platform/actions/workflows/ci.yml/badge.svg)

A backend that turns natural-language requests into structured work. A user talks to an AI **Intake Agent**; each distinct request becomes a **Ticket**, which **Triage** matches to a predefined **Workflow Definition** once it is confident enough, creating a **Workflow Run**.

> **Status:** The Ticket and Workflow Definition APIs persist to Aurora PostgreSQL through SQLAlchemy, using short-lived IAM auth tokens; the schema is managed with Alembic. Workflow Runs can be read and given Required Inputs, and are created by a service Triage will call (see [DESIGN.md](DESIGN.md) §17); the Intake Agent and Triage are not built yet.

## Tech stack

- **Python 3.13**, **FastAPI**, **Pydantic v2**
- **Aurora PostgreSQL 17 Serverless v2** (AWS `us-east-2`)
- **SQLAlchemy 2** over **psycopg 3** with IAM database authentication, **Alembic** migrations
- **Ruff** for lint and format
- **pytest** against a local PostgreSQL 17 in Docker
- **GitHub Actions** runs Ruff, `alembic check` and pytest on every PR

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (never committed):

```bash
AWS_REGION=us-east-2
DB_HOST=<aurora cluster writer endpoint>
DB_PORT=5432
DB_USER=triage_app
DB_NAME=ai_triage
```

Write `KEY=value` with no spaces around `=`, so the file also loads in a shell (`set -a && source .env && set +a`). All five variables are required; the app stops at startup if one is missing. There is no password: each connection uses a short-lived IAM auth token.

To use another PostgreSQL instead of Aurora, set the optional `DATABASE_URL`. The five variables above are then not needed.

AWS credentials come from the default credential chain (e.g. `aws configure`). The IAM identity needs `rds-db:connect` on the `triage_app` database user.

`certs/AmazonRootCA1.pem` is the public root certificate the database's TLS certificate chains to. The app verifies the connection against it; no setup needed.

> **Note:** the AWS account is on the Free plan, where the RDS Query Editor isn't usable. Run admin SQL (users, databases, grants) as `postgres` in AWS CloudShell: open the cluster in the RDS console, go to *Connectivity & security*, and launch CloudShell from there.

## Run

Create or update the database schema, then start the API:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

- Interactive docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Lint and format

With the venv active:

```bash
ruff check .
ruff format .
```

## Test

Tests run against PostgreSQL 17 in Docker, so start Docker first. With the venv active:

```bash
docker compose up -d
pytest
```

`pytest` never touches Aurora. To run the IAM connectivity test deliberately, which wakes the cluster and needs the `.env` above:

```bash
pytest -m aurora
```

To check that every model change has a migration, run this against the local test database. Without `DATABASE_URL`, Alembic connects to Aurora.

```bash
DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/ai_triage_test alembic check
```

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/tickets` | Create a Ticket (`user_id`, `message`) |
| `GET` | `/api/tickets` | List all Tickets |
| `GET` | `/api/tickets/{ticket_id}` | Get one Ticket |
| `PATCH` | `/api/tickets/{ticket_id}` | Update `message` (status is system-managed) |
| `DELETE` | `/api/tickets/{ticket_id}` | Delete a Ticket |
| `POST` | `/api/tickets/{ticket_id}/cancel` | Cancel a Ticket; repeating it succeeds, and a `TRIAGED` or `FAILED` Ticket returns 409 |
| `POST` | `/api/workflow-definitions` | Create a Workflow Definition and its version 1 (`name`, `description`, `confidence_threshold`, `steps`, `required_inputs`, `sample_requests`); a taken name returns 409 |
| `GET` | `/api/workflow-definitions?limit=50&offset=0` | List Workflow Definitions, each with its current version |
| `GET` | `/api/workflow-definitions/{definition_id}` | Get one Workflow Definition with its current version |
| `PATCH` | `/api/workflow-definitions/{definition_id}` | Rename (`name` only; content changes need a new version); a taken name returns 409 |
| `GET` | `/api/workflow-definitions/{definition_id}/versions/{version_number}` | Get one Workflow Definition Version |
| `POST` | `/api/workflow-definitions/{definition_id}/versions` | Publish a new version (full content plus `base_version`, the version that was edited); a `base_version` that isn't current returns 409 |
| `POST` | `/api/workflow-definitions/{definition_id}/disable` | Disable a Workflow Definition so Triage skips it; repeating it succeeds |
| `POST` | `/api/workflow-definitions/{definition_id}/enable` | Enable a Disabled Workflow Definition again; repeating it succeeds |
| `GET` | `/api/workflow-runs/{run_id}` | Get one Workflow Run, with its version's `definition_id` and `version_number`, and the `missing_inputs` it still needs |
| `GET` | `/api/tickets/{ticket_id}/workflow-run` | Get a Ticket's Workflow Run; 404 if the Ticket is missing or hasn't been triaged |
| `POST` | `/api/workflow-runs/{run_id}/inputs` | Submit some or all Required Inputs (`inputs`: values by key); the Run becomes `READY` once all are supplied. Invalid values return 422, and a Run that isn't `AWAITING_INPUTS` returns 409 |

## Project docs

- [DESIGN.md](DESIGN.md): architecture, design decisions and tradeoffs
- [GLOSSARY.md](GLOSSARY.md): domain vocabulary
- [docs/adr/](docs/adr/): architecture decision records
- [.claude/CLAUDE.md](.claude/CLAUDE.md) and [.claude/GUIDELINE.md](.claude/GUIDELINE.md): conventions for AI-assisted development
