---
paths:
  - ".github/workflows/**"
---

# GitHub Actions rules

Rationale is in `DESIGN.md` §14.

- Set `permissions: contents: read` at the top of every workflow. Grant more per job, only when a step needs it.
- Set `timeout-minutes` on every job.
- Use major-version tags for actions (`actions/checkout@v7`). Check the latest release before adding one.
- Never add AWS credentials or OIDC roles for CI. Aurora tests run by hand (see `aws.md`).
- Install from `requirements.txt` in every job, so versions have one source. Don't pin a tool again in the workflow.
- Start the test database with `docker compose up -d --wait`. Don't add a `services:` block, which would repeat `docker-compose.yml`.
- The `test` job needs `DATABASE_URL` in `env:` for Alembic. Without it, `app/database.py` tries to build the IAM engine.
- Run `alembic upgrade head` before `alembic check`, which compares the models with the live schema.
- Don't add path filters. A required check that never starts leaves the PR stuck, and Ruff also formats Markdown.
- Job names are the required check names in the `main` ruleset. Renaming `lint` or `test` means updating the ruleset, or PRs wait on a check that never reports.
- After changing a workflow, confirm that it can still fail, not just that it passes.
