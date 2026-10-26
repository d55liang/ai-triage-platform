import os
from pathlib import Path

import boto3
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Load variables from .env file
load_dotenv()

# AWS Aurora PostgreSQL Serverless
AWS_REGION = os.getenv("AWS_REGION")
DB_CLUSTER_ARN = os.getenv("DB_CLUSTER_ARN")
DB_SECRET_ARN = os.getenv("DB_SECRET_ARN")
DB_NAME = os.getenv("DB_NAME")

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ["DB_PORT"])
DB_USER = os.environ["DB_USER"]

# The gateway's certificate chains to Amazon Root CA 1. psycopg[binary] bundles an
# OpenSSL with no usable default trust store, so sslrootcert=system can't be used.
CA_BUNDLE = Path(__file__).resolve().parent.parent / "certs" / "AmazonRootCA1.pem"

rds_client = boto3.client("rds-data", region_name=AWS_REGION)
rds_auth_client = boto3.client("rds", region_name=AWS_REGION)

engine = create_engine(
    f"postgresql+psycopg://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
    connect_args={"sslmode": "verify-full", "sslrootcert": str(CA_BUNDLE)},
    pool_size=2,
    max_overflow=0,
    pool_pre_ping=True,
)


@event.listens_for(engine, "do_connect")
def _set_iam_token(dialect, conn_rec, cargs, cparams) -> None:
    cparams["password"] = rds_auth_client.generate_db_auth_token(
        DBHostname=DB_HOST, Port=DB_PORT, DBUsername=DB_USER, Region=AWS_REGION
    )


SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def execute_sql(sql: str, parameters: list=None) -> dict:
    response = rds_client.execute_statement(
        resourceArn=DB_CLUSTER_ARN,
        secretArn=DB_SECRET_ARN,
        database=DB_NAME,
        sql=sql,
        parameters=parameters or [],
    )
    return response
