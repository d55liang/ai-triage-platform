from fastapi import FastAPI

from app.routers.ticket_router import ticket_router
from app.routers.workflow_definition_router import workflow_definition_router
from app.routers.workflow_run_router import workflow_run_router

app = FastAPI(title="AI Triage Platform")

app.include_router(ticket_router, prefix="/api")
app.include_router(workflow_definition_router, prefix="/api")
app.include_router(workflow_run_router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
