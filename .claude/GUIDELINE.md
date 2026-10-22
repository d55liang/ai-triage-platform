# Guidelines for Agentic Work

These rules apply to every agent session in this repository. Project facts live in [CLAUDE.md](CLAUDE.md).

## Collaboration mode

This is a personal resume project, so the user must be able to write and defend every line of code.

- **Default: teach, don't do.** Explain the approach, point to the files and lines involved, and let the user implement it.
- **Edit code only when explicitly asked** in the current request. Approval for one change does not carry over to the next.
- **Documentation is the exception.** You may write and update `GLOSSARY.md`, `DESIGN.md`, ADRs, `README.md`, `CLAUDE.md`, this file and `.claude/rules/*` as part of normal work.
- **No AWS changes** (creating, modifying or deleting resources) without explicit approval. Read-only inspection is fine.
- Assignment `.md` files from class are guides, not specifications.

## Code

- Keep code clear and concise. Prefer the shortest version that a reader understands on the first pass; don't trade clarity for brevity.
- Match the surrounding code's style, naming and comment density (see *Coding style* in `CLAUDE.md`).
- Explain anything a reader could find surprising: in a short comment when it belongs in the code, otherwise in your reply.
- Don't add features, abstractions or error handling beyond what the task needs.

## Assumptions and constraints

- State every assumption you make, and verify facts you can check (code, config, AWS) instead of assuming them.
- Keep dependencies minimal. Each new dependency needs a one-line justification, and the rules files and docs must be updated (see below).
- When there are two or more viable approaches, present the **best two** with their tradeoffs and a recommendation. If only one is sensible, say so in one line instead of inventing an alternative.
- If a request is ambiguous in a way that changes the result, ask before acting.

## Documentation

- Keep docstrings and comments clear and concise. Document *why*, not *what* the code already says.
- Use the canonical terms in [GLOSSARY.md](../GLOSSARY.md). When a new domain term appears or an existing one shifts meaning, update the glossary. It holds definitions only, never implementation details.
- When designing or redesigning architecture, update [DESIGN.md](../DESIGN.md) with the decision, why it was made, the alternatives and the tradeoffs. `DESIGN.md` must stay **interview-prep ready**: every section should be something the user can explain and defend out loud.
- Write an ADR in `docs/adr/` only when a decision is hard to reverse, surprising without context, **and** the result of a real tradeoff. Link it from the matching `DESIGN.md` section.

### Keep docs in sync

| Change | Update |
|---|---|
| Technology or dependency added/removed | `.claude/rules/*` (add, edit or delete the file), `requirements.txt`, `CLAUDE.md` tech stack, `README.md` setup |
| Architecture or design choice | `DESIGN.md`, plus an ADR if it meets all three criteria |
| Domain term added or changed | `GLOSSARY.md` |
| Command, env var or setup step added/changed | `CLAUDE.md` commands/environment, `README.md` |
| Milestone started or finished | `CLAUDE.md` current status |
| Endpoint added or changed | `README.md` API section, `DESIGN.md` if it reflects a design choice |
| Convention changed (style, commits, PRs) | `CLAUDE.md`, `.github/pull_request_template.md`, relevant rules file |

**Before calling a task done**, check this table and say which docs you updated, or why none needed it.

## Technology rules

- Each technology in use has a rules file in `.claude/rules/<tech>.md`, path-scoped with `paths:` frontmatter where the rules only apply to some files.
- When a technology is added, write its rules file, starting from widely used community or vendor conventions and adapting them to this codebase. When a technology is removed or replaced, delete or rewrite its file in the same change.
- Rules files hold technology rules only. Project conventions (commit and PR language, domain terms) live in `CLAUDE.md` and `GLOSSARY.md`.
