import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

# Load variables from .env file
load_dotenv()


# The gateway's certificate chains to Amazon Root CA 1. psycopg[binary] bundles an
# OpenSSL with no usable default trust store, so sslrootcert=system can't be used.
CA_BUNDLE = Path(__file__).resolve().parent.parent / "certs" / "AmazonRootCA1.pem"


# AWS Aurora PostgreSQL Serverless
def create_iam_engine() -> Engine:
    """Aurora engine: every new connection gets a fresh IAM auth token."""
    region = os.environ["AWS_REGION"]
    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    user = os.environ["DB_USER"]
    name = os.environ["DB_NAME"]

    rds_auth_client = boto3.client("rds", region_name=region)

    iam_engine = create_engine(
        f"postgresql+psycopg://{user}@{host}:{port}/{name}",
        connect_args={"sslmode": "verify-full", "sslrootcert": str(CA_BUNDLE)},
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )

    @event.listens_for(iam_engine, "do_connect")
    def _set_iam_token(
        dialect: Dialect,
        conn_rec: ConnectionPoolEntry,
        cargs: tuple[Any, ...],
        cparams: dict[str, Any],
    ) -> None:
        cparams["password"] = rds_auth_client.generate_db_auth_token(
            DBHostname=host, Port=port, DBUsername=user, Region=region
        )

    return iam_engine


# Set for local PostgreSQL; unset means Aurora.
DATABASE_URL = os.environ.get("DATABASE_URL")
engine = create_engine(DATABASE_URL) if DATABASE_URL else create_iam_engine()


SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """One transaction per caller: commits if the caller finishes, rolls back if it raises."""
    with SessionLocal.begin() as session:
        yield session


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
