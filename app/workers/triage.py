"""Triage worker: triages each queued Ticket. Run with `python -m app.workers.triage`."""

import asyncio
import logging
import signal
from collections.abc import Callable
from contextlib import AbstractContextManager
from types import FrameType

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.queue import TicketQueuedMessage
from app.providers.factory import build_providers
from app.providers.triage_provider import TriageProvider
from app.queue import TRIAGE_QUEUE_URL, delete_message, receive_message
from app.services.triage_service import claim_ticket, finish_triage, release_claim, score_ticket

# Opens one transaction and commits it on exit: SessionLocal.begin, or a savepoint in tests.
Transaction = Callable[[], AbstractContextManager[Session]]

logger = logging.getLogger(__name__)


def handle_message(
    body: str, providers: list[TriageProvider], runner: asyncio.Runner, transaction: Transaction
) -> None:
    """Triages one message's Ticket. Returning means delete the message; raising means keep it.

    A kept message comes back after the visibility timeout, and after three receives it moves to
    the DLQ (DESIGN.md §18).
    """
    ticket_id = TicketQueuedMessage.model_validate_json(body).payload.ticket_id
    # Committed before scoring, so no transaction is open during the LLM calls.
    with transaction() as session:
        claim = claim_ticket(session, ticket_id)
    if claim is None:
        logger.info(f"Ticket {ticket_id} is claimed elsewhere or has moved on")
        return
    try:
        scores = runner.run(score_ticket(providers, claim.request, claim.candidates))
        with transaction() as session:
            status = finish_triage(session, claim, scores)
    except Exception:
        # Any failure, expected or not: the redelivery can then claim the Ticket at once instead of
        # waiting out the lease. Fenced, so it can't undo another worker's claim. If the release
        # fails too, its error carries this one, and the lease expires on its own.
        with transaction() as session:
            release_claim(session, claim)
        raise
    if status is None:
        logger.info(f"Ticket {ticket_id} lost its claim while scoring")
    else:
        logger.info(f"Ticket {ticket_id} is {status}")


def run() -> None:
    # Raises at startup for a bad TRIAGE_PROVIDERS or a missing Gemini key, not on the first Ticket.
    providers = build_providers()
    stopping = False

    def stop(signum: int, frame: FrameType | None) -> None:
        # Finish the current message first. Installed before the Runner starts, so the Runner keeps
        # this handler instead of turning Ctrl-C into a cancellation.
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    # One event loop for the worker's lifetime, so the SDKs' async clients keep their connections.
    with asyncio.Runner() as runner:
        while not stopping:
            try:
                # Long polling, with no transaction open while it waits.
                message = receive_message(TRIAGE_QUEUE_URL)
                if message is None:
                    continue
                handle_message(message.body, providers, runner, SessionLocal.begin)
                # Only after handle_message's transactions committed. If this delete fails, the
                # redelivery finds the Ticket finished, claims nothing and is deleted then.
                delete_message(TRIAGE_QUEUE_URL, message.receipt_handle)
            except Exception:
                # The worker must outlive a failed attempt or an outage; the message is redelivered.
                logger.exception("Triaging a message failed; it will be redelivered")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run()
