# Git rules

Commit-message and PR wording conventions live in `CLAUDE.md`; this file covers Git mechanics only.

- Never commit, push, merge or open a PR unless the user asks in the current request.
- Branch from an up-to-date `main`. Name branches `<type>/<short-kebab-description>` (`feat/aurora-postgresql`, `fix/ticket-404`), with the same types as commits.
- Never commit to `main` directly. Never force-push `main`; force-push your own branch only with `--force-with-lease`.
- Keep commits small and focused: one logical change per commit, and the app should run at every commit.
- Stage files explicitly (`git add <path>`); review `git diff --staged` before committing.
- Never commit `.env`, `venv/`, `__pycache__/`, credentials or tokens. Add new local-only files to `.gitignore` in the same change.
- Update the branch with the latest `main` before opening a PR, and resolve conflicts on the branch, not on `main`.
- Never rewrite history that has already been pushed and shared (no rebasing or amending pushed commits on shared branches).
- Don't use interactive flags (`-i`); they aren't supported in this environment.
