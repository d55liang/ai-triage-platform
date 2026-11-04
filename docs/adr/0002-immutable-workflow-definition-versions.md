---
status: accepted
---

# Immutable Workflow Definition Versions

An Admin never edits a Workflow Definition in place. Every change publishes a new, immutable Workflow Definition Version, and a Workflow Run references the exact version it started from. Identity (`workflow_definitions`) is split from content (`workflow_definition_versions`). Running work then never changes under a Run, Triage never reads a half-edited definition, and the history of every threshold and step list is kept. Workflow Definitions are disabled, never deleted, so no version a Run references can disappear.

## Considered options

- **Edit in place and snapshot onto each Run:** one simple table, but every Run duplicates the content, and definitions that never got a Run keep no history.
- **Edit in place with no snapshot:** simplest, but running work silently changes and history is lost.

## Consequences

- Reversing this later means migrating every Workflow Run's foreign key, so it's hard to undo once Runs exist.
- Even a typo fix creates a version. Rollback publishes old content as a new version. The current version is the highest `version_number`, with no pointer.
- Concurrent edits are optimistic: a new version names its `base_version`, and `UNIQUE (definition_id, version_number)` rejects the loser of a race with a 409.
