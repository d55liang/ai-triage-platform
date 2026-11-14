"""Outbox relay: publishes saved events to SQS. Run with `python -m app.workers.relay`."""

import logging
import signal
import time
from types import FrameType

from app.database import SessionLocal
from app.services.outbox_service import BATCH_SIZE, publish_pending_events

POLL_INTERVAL_SECONDS = 1.0

logger = logging.getLogger(__name__)


def run() -> None:
    stopping = False

    def stop(signum: int, frame: FrameType | None) -> None:
        # Finish the current batch, so an event is never sent without being marked published.
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while not stopping:
        try:
            # One transaction per batch: the row locks last only as long as one send.
            with SessionLocal.begin() as session:
                sent = publish_pending_events(session)
        except Exception:
            # The relay must outlive a database or SQS outage; unsent events stay in the outbox.
            logger.exception("Publishing outbox events failed; retrying")
            sent = 0
        if sent:
            logger.info(f"Published {sent} outbox events")
        # A full batch suggests more are waiting, so go again without sleeping.
        if sent < BATCH_SIZE:
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run()
