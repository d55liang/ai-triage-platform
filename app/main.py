from fastapi import FastAPI

from app.routers.ticket_router import ticket_router

app = FastAPI(title="AI Triage Platform")

app.include_router(ticket_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
