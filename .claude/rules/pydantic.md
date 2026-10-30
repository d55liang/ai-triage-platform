---
paths:
  - "app/models/**/*.py"
  - "app/routers/**/*.py"
---

# Pydantic rules (v2)

- Request bodies live in `app/models/request.py`, responses in `app/models/response.py`. Never reuse one model for both directions.
- Naming: `<Action><Resource>Request` (e.g. `CreateTicketRequest`), `<Resource>Item` for a single resource, `<Resource>sResponse` with a `data: list[...]` field for collections.
- Declare every field as `Annotated[<type>, Field(description="...")]`; descriptions appear in `/docs`.
- Optional fields that may legitimately be null are typed `X | None` with a `None` default.
- Exception, PATCH bodies: a field that may be omitted but must never be null (it maps to a `NOT NULL` column) is typed `X` with a `None` default, and the router uses `model_dump(exclude_unset=True)`. Pydantic doesn't validate defaults, so omission works, and an explicit `null` is rejected with 422 instead of failing in the database with 500 (see `DESIGN.md` *Known gaps*).
- Enum fields use `StrEnum` classes from `app/models/enums.py`, shared by request, response and ORM models.
- Use constrained types and `Field` constraints (`min_length`, `max_length`, `ge`, ...) instead of hand-written validation.
- Use `Enum` / `Literal` for closed sets such as Ticket Status once they're defined.
- Use v2 APIs only: `model_dump`, `model_validate`, `field_validator`, `model_config`. No v1 `dict()`, `parse_obj`, `@validator` or `class Config`.
- Use `model_config = ConfigDict(from_attributes=True)` on response models that are built from ORM objects.
- Validate at the edge: once a request model is parsed, downstream layers trust it.
