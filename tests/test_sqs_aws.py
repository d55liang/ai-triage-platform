"""The real SQS queues: settings that must match elasticmq.conf, and the IAM policy's permissions.

Marked aws and run only with pytest -m aws, with no workers running: the test message isn't a
ticket.queued envelope.
"""

import json
import os
from uuid import uuid4

import boto3
import pytest
from botocore.client import BaseClient

from app.queue import delete_message, receive_message, send_messages
from app.services.triage_service import CLAIM_LEASE

pytestmark = pytest.mark.aws


@pytest.fixture(scope="module")
def aws_sqs() -> BaseClient:
    # Without endpoint_url: conftest.py points app.queue's client at ElasticMQ.
    return boto3.client("sqs", region_name=os.environ["AWS_REGION"])


@pytest.fixture(scope="module")
def triage_url(aws_sqs: BaseClient) -> str:
    # Looked up by name, since conftest.py also forces TRIAGE_QUEUE_URL to ElasticMQ.
    return aws_sqs.get_queue_url(QueueName="triage")["QueueUrl"]


@pytest.fixture(scope="module")
def dlq_url(aws_sqs: BaseClient) -> str:
    return aws_sqs.get_queue_url(QueueName="triage-dlq")["QueueUrl"]


def attributes(aws_sqs: BaseClient, queue_url: str) -> dict[str, str]:
    return aws_sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["All"])["Attributes"]


# Expected values are those in elasticmq.conf and infra/triage-queues.yaml.
def test_triage_queue_matches_local(aws_sqs: BaseClient, triage_url: str) -> None:
    triage = attributes(aws_sqs, triage_url)
    redrive = json.loads(triage["RedrivePolicy"])

    assert int(triage["VisibilityTimeout"]) == 60
    # A redelivery after a crash must find the lease expired, or it can't take the Ticket over.
    assert CLAIM_LEASE.total_seconds() < int(triage["VisibilityTimeout"])
    assert redrive["maxReceiveCount"] == 3
    assert redrive["deadLetterTargetArn"].endswith(":triage-dlq")


def test_dlq_keeps_dead_letters_from_triage_only(aws_sqs: BaseClient, dlq_url: str) -> None:
    dlq = attributes(aws_sqs, dlq_url)
    allow = json.loads(dlq["RedriveAllowPolicy"])

    assert int(dlq["MessageRetentionPeriod"]) == 14 * 24 * 60 * 60
    assert allow["redrivePermission"] == "byQueue"
    assert len(allow["sourceQueueArns"]) == 1
    assert allow["sourceQueueArns"][0].endswith(":triage")


def test_dlq_consumer_can_receive(
    aws_sqs: BaseClient, dlq_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.queue.sqs_client", aws_sqs)

    # Only the permission is checked: AccessDenied would raise. The DLQ may hold real dead letters,
    # and one received here comes back after its visibility timeout.
    receive_message(dlq_url, wait_seconds=1)


def test_app_round_trip(
    aws_sqs: BaseClient, triage_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    triage = attributes(aws_sqs, triage_url)
    waiting = int(triage["ApproximateNumberOfMessages"])
    in_flight = int(triage["ApproximateNumberOfMessagesNotVisible"])
    # Otherwise the receive below could take a real Ticket's message.
    assert waiting + in_flight == 0, "the triage queue isn't empty; stop the relay and run later"
    monkeypatch.setattr("app.queue.sqs_client", aws_sqs)
    body = json.dumps({"aws_test": str(uuid4())})

    # The relay's call: SendMessageBatch, which sqs:SendMessage covers.
    assert send_messages(triage_url, {"aws-test": body}) == ["aws-test"]
    message = receive_message(triage_url, wait_seconds=5)

    assert message is not None
    # Not deleted unless it's ours: anything else reappears after the visibility timeout.
    assert message.body == body, "received a message this test didn't send; left it in the queue"
    delete_message(triage_url, message.receipt_handle)
