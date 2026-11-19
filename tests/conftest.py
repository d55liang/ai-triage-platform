import os

# Hard-set, not setdefault: nothing in the shell or .env may point tests at Aurora.
os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres@127.0.0.1:5433/ai_triage_test"
# Likewise for SQS: ElasticMQ from docker-compose.yml, never AWS.
os.environ["SQS_ENDPOINT_URL"] = "http://127.0.0.1:9324"
os.environ["TRIAGE_QUEUE_URL"] = "http://127.0.0.1:9324/000000000000/triage"
os.environ["TRIAGE_DLQ_URL"] = "http://127.0.0.1:9324/000000000000/triage-dlq"
os.environ["AWS_REGION"] = "us-east-2"

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import Transaction, engine, get_session
from app.main import app
from app.queue import TRIAGE_DLQ_URL, TRIAGE_QUEUE_URL, sqs_client

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture(scope="session", autouse=True)
def migrated_database(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")


@pytest.fixture
def empty_queues() -> Iterator[None]:
    """The queues aren't rolled back with the database, so a test starts and ends with them empty."""
    for queue_url in (TRIAGE_QUEUE_URL, TRIAGE_DLQ_URL):
        sqs_client.purge_queue(QueueUrl=queue_url)
    yield
    for queue_url in (TRIAGE_QUEUE_URL, TRIAGE_DLQ_URL):
        sqs_client.purge_queue(QueueUrl=queue_url)


@pytest.fixture
def session() -> Iterator[Session]:
    """Shared with `client`, so a test can set up states the API can't reach yet."""
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """API client whose writes are all undone: nothing below this session ever commits."""

    def override_get_session() -> Iterator[Session]:
        # A savepoint stands in for the real commit: it flushes on success and
        # rolls back only this request on failure.
        try:
            with session.begin_nested():
                yield session
        except Exception:
            # A rolled-back savepoint can leave objects that UPDATE ... RETURNING refreshed in the
            # identity map; a real request would start with a fresh session and never see them.
            session.expire_all()
            raise

    app.dependency_overrides[get_session] = override_get_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def transaction(session: Session) -> Transaction:
    """Stands in for SessionLocal.begin in worker tests: a savepoint on the test session, so each of
    the worker's commits is undone with the test."""

    @contextmanager
    def savepoint() -> Iterator[Session]:
        try:
            with session.begin_nested():
                yield session
        except Exception:
            # As in the client override: drop values a rolled-back UPDATE ... RETURNING refreshed.
            session.expire_all()
            raise

    return savepoint
