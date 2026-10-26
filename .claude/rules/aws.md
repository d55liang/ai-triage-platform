# AWS rules

## Agent safety

- **Never create, modify or delete AWS resources without explicit approval** for that specific change. Read-only inspection (`Describe*`, `List*`, `Get*`) is fine.
- The account is restricted by an organisation policy; resources live in **`us-east-2`**. Don't assume other regions or services are available.
- The account is on the **AWS Free plan**, and the RDS Query Editor isn't usable on it. Don't tell the user to run SQL there. Run admin SQL (users, grants, databases) as `postgres` in **AWS CloudShell**, launched from the cluster's *Connectivity & security* tab while signed in to the console as root. The Data API is not an option: it needs a Secrets Manager secret, which express clusters don't support. CloudShell's `psql` is older than the server (17), so some `\` meta-commands (`\l`, `\du`) fail or show incomplete output; use plain SQL against `pg_database` / `pg_roles`.
- On Aurora, `postgres` is not a true superuser. To create a database owned by another role, first `GRANT <role> TO postgres WITH SET TRUE, INHERIT FALSE`.
- Prefer the AWS MCP server's tools over running the AWS CLI through Bash.

## Credentials & secrets

- Never hard-code or commit credentials, ARNs, hosts or tokens. Load them from `.env` locally (gitignored) and from the environment in deployment.
- Use the default boto3 credential chain; never pass access keys explicitly in code.
- Least privilege: IAM policies grant only the actions and resources needed (e.g. `rds-db:connect` on the specific `dbuser` ARN).

## Aurora & IAM database auth

- Create boto3 clients once per process, with an explicit `region_name`.
- Generate IAM auth tokens with `rds.generate_db_auth_token(...)`. A token is valid for **15 minutes** for *opening* a connection; generate a fresh one for every new connection (SQLAlchemy `do_connect` event), never once at startup.
- The cluster uses **express configuration**: no VPC, no subnet group, no security groups. Clients connect over the internet through Aurora's **internet access gateway**, which accepts **IAM authentication only**. `PubliclyAccessible: false` on the instance is expected and irrelevant (see ADR 0001).
- Don't try to add security groups, IP allowlists, VPC settings, password auth, Secrets Manager credentials or RDS Proxy. Express clusters support none of them. A private network requires a new cluster created with full configuration.
- Connect as a dedicated app user that has `GRANT rds_iam`, never as the `postgres` master user. Removing `rds_iam` from the master user locks out new connections.
- Always use TLS with `sslmode=verify-full`. The gateway's certificate chains to **Amazon Root CA 1** (public ACM chain), not the RDS CA bundle. Pin trust to `certs/AmazonRootCA1.pem` via `sslrootcert` with an absolute path. Don't use `sslrootcert=system`: the OpenSSL bundled with `psycopg[binary]` has no usable default trust store, so every verification fails. (Homebrew `psql` links its own OpenSSL, so `system` does work there.)
- Serverless v2 auto-pauses after 300 s idle; idle pooled connections prevent it. Keep pools small, and expect a cold start of several seconds after a pause.
- Run AWS-dependent tests deliberately and sparingly to control cost; everything else runs against local PostgreSQL.
