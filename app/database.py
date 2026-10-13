import boto3
import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

# AWS Aurora PostgreSQL Serverless
AWS_REGION = os.getenv("AWS_REGION")
DB_CLUSTER_ARN = os.getenv("DB_CLUSTER_ARN")
DB_SECRET_ARN = os.getenv("DB_SECRET_ARN")
DB_NAME = os.getenv("DB_NAME")

rds_client = boto3.client("rds-data", region_name=AWS_REGION)

def execute_sql(sql: str, parameters: list=None) -> dict:
    response = rds_client.execute_statement(
        resourceArn=DB_CLUSTER_ARN,
        secretArn=DB_SECRET_ARN,
        database=DB_NAME,
        sql=sql,
        parameters=parameters or [],
    )
    return response
