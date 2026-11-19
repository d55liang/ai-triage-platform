import os
from dataclasses import dataclass

import boto3
from dotenv import load_dotenv

load_dotenv()


# Set for ElasticMQ in tests and local development; unset means AWS.
sqs_client = boto3.client(
    "sqs",
    region_name=os.environ["AWS_REGION"],
    endpoint_url=os.environ.get("SQS_ENDPOINT_URL"),
)

TRIAGE_QUEUE_URL = os.environ["TRIAGE_QUEUE_URL"]
TRIAGE_DLQ_URL = os.environ["TRIAGE_DLQ_URL"]


@dataclass(frozen=True)
class ReceivedMessage:
    body: str
    # Needed to delete the message; valid only for this receive.
    receipt_handle: str


def send_messages(queue_url: str, messages: dict[str, str]) -> list[str]:
    """Sends at most 10 message bodies, keyed by ID, in one call; returns the IDs SQS accepted.

    A batch can partly fail, so callers must treat only the returned IDs as sent.
    """
    response = sqs_client.send_message_batch(
        QueueUrl=queue_url,
        Entries=[{"Id": key, "MessageBody": body} for key, body in messages.items()],
    )
    return [entry["Id"] for entry in response.get("Successful", [])]


def receive_message(queue_url: str, wait_seconds: int = 20) -> ReceivedMessage | None:
    """One message, long-polling up to wait_seconds; None if none arrived.

    One at a time: the visibility timeout starts at receive, so a batch handled one by one would
    let the later messages reappear before they were reached (DESIGN.md §18).
    """
    response = sqs_client.receive_message(
        QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=wait_seconds
    )
    messages = response.get("Messages", [])
    if not messages:
        return None
    return ReceivedMessage(messages[0]["Body"], messages[0]["ReceiptHandle"])


def delete_message(queue_url: str, receipt_handle: str) -> None:
    sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
