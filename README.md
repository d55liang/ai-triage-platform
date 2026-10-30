# AI Triage Platform

A backend that turns natural-language requests into structured work. A user talks to an AI **Intake Agent**; each distinct request becomes a **Ticket**, which **Triage** matches to a predefined **Workflow Definition** once it is confident enough, creating a **Workflow Run**.

> **Status:** The Ticket CRUD API persists to Aurora PostgreSQL through SQLAlchemy, using short-lived IAM auth tokens; the schema is managed with Alembic. The agent and workflows are not built yet.

## Tech stack

- **Python 3.13**, **FastAPI**, **Pydantic v2**
- **Aurora PostgreSQL 17 Serverless v2** (AWS `us-east-2`)
- **SQLAlchemy 2** over **psycopg 3** with IAM database authentication, **Alembic** migrations
- Planned: Ruff, pytest

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (never committed):

```bash
AWS_REGION=us-east-2
DB_CLUSTER_ARN=<aurora cluster ARN>
DB_SECRET_ARN=<secrets manager ARN>
DB_NAME=<database name>
```

AWS credentials come from the default credential chain (e.g. `aws configure`).

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

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/tickets` | Create a Ticket (`user_id`, `message`) |
| `GET` | `/api/tickets` | List all Tickets |
| `GET` | `/api/tickets/{ticket_id}` | Get one Ticket |
| `PATCH` | `/api/tickets/{ticket_id}` | Update `message` (status is system-managed) |
| `DELETE` | `/api/tickets/{ticket_id}` | Delete a Ticket |

## Project docs

- [DESIGN.md](DESIGN.md): architecture, design decisions and tradeoffs
- [GLOSSARY.md](GLOSSARY.md): domain vocabulary
- [docs/adr/](docs/adr/): architecture decision records
- [.claude/CLAUDE.md](.claude/CLAUDE.md) and [.claude/GUIDELINE.md](.claude/GUIDELINE.md): conventions for AI-assisted development
