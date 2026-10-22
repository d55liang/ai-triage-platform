---
status: accepted
---

# Direct IAM-auth connections instead of the RDS Data API

We are replacing the RDS Data API with direct `psycopg` connections authenticated by short-lived IAM auth tokens, accessed through SQLAlchemy (ORM for routine CRUD, Core for complex queries) and migrated with Alembic. SQLAlchemy and Alembic need a standard driver; the only Data API dialect (`sqlalchemy-aurora-data-api`) is third-party and was last released in Dec 2023. A standard driver also lets most tests run against a local PostgreSQL.

## Considered options

- **Keep the Data API:** no networking or pooling to manage, but it ties the data layer and migrations to a stale dialect and to the Data API's own value format. It also can't authenticate to this cluster: every call needs a Secrets Manager secret, which express configuration doesn't support.
- **Password authentication (e.g. from Secrets Manager):** not available. The cluster uses Aurora express configuration, whose internet access gateway accepts IAM authentication only.

## Consequences

- The app owns connection pooling and must generate a fresh token for each new connection.
- Network access comes from the express configuration's internet access gateway. The cluster has no VPC, so there are no security groups and no IP allowlist: the endpoint is internet-reachable, and IAM auth plus TLS is the only protection. This is by design. Don't try to "lock it down" with a security group or VPC setting, because express clusters support neither. A private network requires a new cluster created with full configuration.
- Every database user the app connects as must have the `rds_iam` role, and the IAM identity needs `rds-db:connect` on that user.
- Idle pooled connections stop Serverless v2 from auto-pausing.
