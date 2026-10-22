---
paths:
  - "app/main.py"
  - "app/routers/**/*.py"
---

# FastAPI rules

- One `APIRouter` per resource in `app/routers/<resource>_router.py`, with `prefix` and `tags`; register it in `app/main.py` under the `/api` prefix.
- Route handlers stay thin: parse input, call one service function, map errors to HTTP. No SQL and no business rules in routers.
- Every route declares `response_model` and an explicit `status_code` (201 for create, 200 for read/update/delete).
- Use REST verbs: `POST` create, `GET` read, `PATCH` partial update, `DELETE` remove. Collection paths have no trailing slash (`""`).
- Type path IDs as `uuid.UUID` so malformed IDs return 422 automatically; pass `str(id)` down to the service.
- Translate domain errors to `HTTPException` in the router only, with a clear `detail` message and `raise ... from e`. Missing resource → 404.
- For `PATCH`, use `request.model_dump(exclude_unset=True)` so omitted fields aren't overwritten.
- Use `def` handlers while the database client is synchronous. Switch to `async def` only with an async driver, never by calling blocking I/O inside `async def`.
- Use dependencies (`Depends`) for cross-cutting concerns such as DB sessions and auth once they exist, not module globals inside handlers.
- Keep `/health` free of any dependency on the database so it reports process liveness.
