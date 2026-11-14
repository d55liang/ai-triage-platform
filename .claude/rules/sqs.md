---
paths:
  - "app/queue.py"
  - "app/workers/**/*.py"
  - "app/services/outbox_service.py"
  - "elasticmq.conf"
  - "docker-compose.yml"
---

# Amazon SQS rules

Rationale is in `DESIGN.md` §18.

## Client

- One SQS client per process, created in `app/queue.py` with an explicit `region_name`, the same way `app/database.py` holds the engine. Queue URLs are read there too.
- `SQS_ENDPOINT_URL` set means ElasticMQ; unset means AWS. Never hard-code an endpoint or queue URL outside `tests/conftest.py`.
- Use the default boto3 credential chain. Only CI sets dummy keys, because boto3 won't sign requests without some and ElasticMQ ignores them.

## Publishing

- Only the outbox relay sends messages. Application code never calls SQS directly in a request; it writes an outbox event in the same transaction as its change (`DESIGN.md` §18).
- Send with `send_message_batch`, at most 10 entries per call. A batch can partly fail: treat only the IDs in `Successful` as sent, and leave the rest unpublished for the next batch. Never send an empty batch.
- Message bodies are the JSON envelope `{"event_id", "event_type", "payload"}`. Payloads carry IDs, not copies of rows, so a message can't go stale.

## Consuming

- Delivery is at least once and unordered (standard queues). Every consumer must be idempotent, which here means a compare-and-set on the row's status.
- Delete a message only after the transaction that handled it has committed. A message that isn't deleted comes back after the visibility timeout; after `maxReceiveCount` receives it moves to the DLQ.
- Never hold a database transaction open while waiting on `receive_message` (long polling).

## Queues

- Queues are declared in `elasticmq.conf` for local use, with the same names, visibility timeout and DLQ redrive as AWS. Change both together.
- Creating or changing queues, DLQs or their IAM policies in AWS needs explicit approval (`aws.md`).

## Tests

- Tests use ElasticMQ from `docker-compose.yml` on `127.0.0.1:9324`; `tests/conftest.py` hard-sets the endpoint and queue URLs, as it does for `DATABASE_URL`.
- The queue isn't rolled back with the database. A test that sends or receives purges the queue before and after itself.
