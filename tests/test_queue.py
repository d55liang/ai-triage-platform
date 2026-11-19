"""Receiving and deleting messages, against ElasticMQ."""

import pytest

from app.queue import TRIAGE_QUEUE_URL, delete_message, receive_message, sqs_client

pytestmark = pytest.mark.usefixtures("empty_queues")


def count_messages(queue_url: str) -> int:
    """Visible and in-flight messages, so a received but undeleted message still counts."""
    attributes = sqs_client.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return sum(int(value) for value in attributes.values())


def test_receive_returns_the_message() -> None:
    sqs_client.send_message(QueueUrl=TRIAGE_QUEUE_URL, MessageBody='{"a": 1}')

    message = receive_message(TRIAGE_QUEUE_URL, wait_seconds=1)

    assert message is not None
    assert message.body == '{"a": 1}'
    assert message.receipt_handle


def test_receive_from_empty_queue_returns_none() -> None:
    assert receive_message(TRIAGE_QUEUE_URL, wait_seconds=1) is None


def test_deleted_message_is_gone() -> None:
    sqs_client.send_message(QueueUrl=TRIAGE_QUEUE_URL, MessageBody='{"a": 1}')
    message = receive_message(TRIAGE_QUEUE_URL, wait_seconds=1)
    assert message is not None
    assert count_messages(TRIAGE_QUEUE_URL) == 1

    delete_message(TRIAGE_QUEUE_URL, message.receipt_handle)

    assert count_messages(TRIAGE_QUEUE_URL) == 0
