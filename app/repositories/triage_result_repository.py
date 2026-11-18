from sqlalchemy.orm import Session

from app.models.orm import TriageResult


def save_triage_results(session: Session, results: list[dict]) -> None:
    session.add_all([TriageResult(**result) for result in results])
    session.flush()
