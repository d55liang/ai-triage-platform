---
paths:
  - "app/models/**/*.py"
  - "app/routers/**/*.py"
---

# Pydantic rules (v2)

- Request bodies live in `app/models/request.py`, responses in `app/models/response.py`. Never reuse one model for both directions.
- Naming: `<Action><Resource>Request` (e.g. `CreateTicketRequest`), `<Resource>Item` for a single resource, `<Resource>sResponse` with a `data: list[...]` field for collections.
- Declare every field as `Annotated[<type>, Field(description="...")]`; descriptions appear in `/docs`.
- Optional fields are typed `X | None` with a `None` default. Don't type a field `str` and default it to `None`.
- Use constrained types and `Field` constraints (`min_length`, `max_length`, `ge`, ...) instead of hand-written validation.
- Use `Enum` / `Literal` for closed sets such as Ticket Status once they're defined.
- Use v2 APIs only: `model_dump`, `model_validate`, `field_validator`, `model_config`. No v1 `dict()`, `parse_obj`, `@validator` or `class Config`.
- Use `model_config = ConfigDict(from_attributes=True)` on response models that are built from ORM objects.
- Validate at the edge: once a request model is parsed, downstream layers trust it.
