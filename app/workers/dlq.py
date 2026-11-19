"""DLQ consumer: fails Tickets whose triage retries are used up. Run `python -m app.workers.dlq`."""

import logging
import signal
from types import FrameType

from pydantic import ValidationError

from app.database import SessionLocal, Transaction
from app.models.queue import TicketQueuedMessage
from app.queue import TRIAGE_DLQ_URL, delete_message, receive_message
from app.services.triage_service import fail_ticket

logger = logging.getLogger(__name__)


def handle_dead_letter(body: str, transaction: Transaction) -> None:
    """Fails the message's Ticket. Returning means delete the message; raising means keep it.

    Only an outage raises: every outcome returns, since a dead letter has nowhere further to go.
    Keeping one on an outage matters, or its Ticket would stay QUEUED or TRIAGING for good.
    """
    try:
        ticket_id = TicketQueuedMessage.model_validate_json(body).payload.ticket_id
    except ValidationError:
        logger.exception(f"Dropping a dead letter that isn't a ticket.queued event: {body!r}")
        return
    with transaction() as session:
        failed = fail_ticket(session, ticket_id)
    if failed:
        # The one Triage outcome that needs a person.
        logger.error(f"Ticket {ticket_id} is FAILED: its triage retries are used up")
    else:
        logger.info(f"Ticket {ticket_id} had already moved on")


def run() -> None:
    stopping = False

    def stop(signum: int, frame: FrameType | None) -> None:
        # Finish the current message, so a Ticket is never failed without its message deleted.
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while not stopping:
        try:
            # Long polling, with no transaction open while it waits.
            message = receive_message(TRIAGE_DLQ_URL)
            if message is None:
                continue
            handle_dead_letter(message.body, SessionLocal.begin)
            # Only after the commit. If this delete fails, the redelivery finds the Ticket FAILED,
            # changes nothing and is deleted then.
            delete_message(TRIAGE_DLQ_URL, message.receipt_handle)
        except Exception:
            # The consumer must outlive an outage; the dead letter comes back after its visibility
            # timeout.
            logger.exception("Handling a dead letter failed; it will be redelivered")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run()
