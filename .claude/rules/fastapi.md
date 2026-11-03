---
paths:
  - "app/main.py"
  - "app/routers/**/*.py"
---

# FastAPI rules

- One `APIRouter` per resource in `app/routers/<resource>_router.py`, with `prefix` and `tags`; register it in `app/main.py` under the `/api` prefix.
- Route handlers stay thin: parse input, call one service function, map errors to HTTP. No SQL and no business rules in routers.
- Every route declares `response_model` and an explicit `status_code` (201 for create, 200 for read/update/delete).
- Use REST verbs: `POST` create, `GET` read, `PATCH` partial update, `DELETE` remove. Collection paths have no trailing slash (`""`). A domain action that isn't plain CRUD is a `POST` to a sub-path that returns 200 (`POST /tickets/{ticket_id}/cancel`).
- Type path IDs as `uuid.UUID` so malformed IDs return 422 automatically, and pass the `UUID` through to the service and repository unchanged (no `str(...)`).
- Translate domain errors to `HTTPException` in the router only, with a clear `detail` message and `raise ... from e`. Missing resource → 404.
- For `PATCH`, use `request.model_dump(exclude_unset=True)` so omitted fields aren't overwritten.
- Use `def` handlers while the database client is synchronous. Switch to `async def` only with an async driver, never by calling blocking I/O inside `async def`.
- Use dependencies (`Depends`) for cross-cutting concerns such as DB sessions and auth, not module globals inside handlers. Handlers that touch the database take `session: SessionDep` (from `app/dependencies.py`) and pass it to the service.
- Keep `/health` free of any dependency on the database so it reports process liveness.
