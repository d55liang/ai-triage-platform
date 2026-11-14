import os

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


def send_messages(queue_url: str, messages: dict[str, str]) -> list[str]:
    """Sends at most 10 message bodies, keyed by ID, in one call; returns the IDs SQS accepted.

    A batch can partly fail, so callers must treat only the returned IDs as sent.
    """
    response = sqs_client.send_message_batch(
        QueueUrl=queue_url,
        Entries=[{"Id": key, "MessageBody": body} for key, body in messages.items()],
    )
    return [entry["Id"] for entry in response.get("Successful", [])]
