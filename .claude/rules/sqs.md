---
paths:
  - "app/queue.py"
  - "app/workers/**/*.py"
  - "app/services/outbox_service.py"
  - "elasticmq.conf"
  - "docker-compose.yml"
  - "infra/triage-queues.yaml"
---

# Amazon SQS rules

Rationale is in `DESIGN.md` §18.

## Client

- One SQS client per process, created in `app/queue.py` with an explicit `region_name`, the same way `app/database.py` holds the engine. Queue URLs (`TRIAGE_QUEUE_URL`, `TRIAGE_DLQ_URL`) are read there too, as required variables.
- Only `app/queue.py` touches boto3's response shapes. It returns plain values (`send_messages` the accepted IDs, `receive_message` a `ReceivedMessage` or `None`).
- `SQS_ENDPOINT_URL` set means ElasticMQ; unset means AWS. Never hard-code an endpoint or queue URL outside `tests/conftest.py`.
- Use the default boto3 credential chain. Only CI sets dummy keys, because boto3 won't sign requests without some and ElasticMQ ignores them.

## Publishing

- Only the outbox relay sends messages. Application code never calls SQS directly in a request; it writes an outbox event in the same transaction as its change (`DESIGN.md` §18).
- Send with `send_message_batch`, at most 10 entries per call. A batch can partly fail: treat only the IDs in `Successful` as sent, and leave the rest unpublished for the next batch. Never send an empty batch.
- Message bodies are the JSON envelope `{"event_id", "event_type", "payload"}`. Payloads carry IDs, not copies of rows, so a message can't go stale.

## Consuming

- Receive one message at a time (`MaxNumberOfMessages=1`) with long polling (`WaitTimeSeconds=20`). The visibility timeout starts at receive, so a batch handled one by one lets later messages reappear and spends their receives. Scale with more processes.
- Delivery is at least once and unordered (standard queues). Every consumer must be idempotent, which here means a compare-and-set on the row's status.
- Delete a message only after the transaction that handled it has committed. A message that isn't deleted comes back after the visibility timeout; after `maxReceiveCount` receives it moves to the DLQ.
- Never hold a database transaction open while waiting on `receive_message` (long polling).
- The DLQ consumer deletes a dead letter after every outcome, malformed bodies included, since it has nowhere further to go. Only an exception (an outage) keeps it.

## Queues

- Queues are declared twice, with the same names, visibility timeout and DLQ redrive: `elasticmq.conf` for local use and `infra/triage-queues.yaml` for AWS. Change both together.
- Creating or changing queues, DLQs or their IAM policies in AWS needs explicit approval (`aws.md`).

## Tests

- Tests use ElasticMQ from `docker-compose.yml` on `127.0.0.1:9324`; `tests/conftest.py` hard-sets the endpoint and queue URLs, as it does for `DATABASE_URL`.
- The queues aren't rolled back with the database. A test that sends or receives uses the `empty_queues` fixture from `tests/conftest.py`, which purges both queues before and after it.
