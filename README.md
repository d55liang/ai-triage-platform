# Daniel AI Triage Platform — Starter Code

This starter project accompanies the in-class Ticket Service assignment.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

Open:

- http://localhost:8000/health
- http://localhost:8000/docs

## In-Class Task

Implement `create_ticket()` in:

```text
app/services/ticket_service.py
```

The method should:

1. Generate a UUID
2. Create a ticket
3. Set `status = "CREATED"`
4. Save it through `ticket_repository`
5. Return the saved ticket

Then test:

```text
POST /tickets
```
