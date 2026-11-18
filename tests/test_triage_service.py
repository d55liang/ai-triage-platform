"""Triage service tests. No worker exists yet, so they call the service directly.

Inside a test's transaction now() never changes, so a lease can't expire by waiting: tests move
claimed_at back by hand instead. Scoring is async, so its tests run it with asyncio.run.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.enums import TicketStatus
from app.models.orm import (
    Ticket,
    TriageResult,
    WorkflowDefinition,
    WorkflowDefinitionVersion,
    WorkflowRun,
)
from app.models.triage import Candidate, MatchResult
from app.repositories.workflow_definition_repository import DefinitionWithVersion
from app.services.triage_service import (
    Claim,
    ProviderScores,
    claim_ticket,
    finish_triage,
    release_claim,
    score_ticket,
)

TICKET = {"user_id": "user-1", "message": "My laptop died, I need a new one"}
WORKFLOW_DEFINITION = {
    "name": "Laptop Request",
    "description": "Order a new laptop for the User",
    "confidence_threshold": "0.80",
    "steps": [{"name": "Place order", "instructions": "Order the laptop from the approved vendor"}],
    "required_inputs": [],
    "sample_requests": ["My laptop died, I need a new one"],
}


def create_ticket(client: TestClient) -> UUID:
    response = client.post("/api/tickets", json=TICKET)
    assert response.status_code == 201
    return UUID(response.json()["ticket_id"])


def create_definition(client: TestClient, name: str) -> UUID:
    response = client.post("/api/workflow-definitions", json={**WORKFLOW_DEFINITION, "name": name})
    assert response.status_code == 201
    return UUID(response.json()["definition_id"])


def get_ticket_status(client: TestClient, ticket_id: UUID) -> str:
    response = client.get(f"/api/tickets/{ticket_id}")
    assert response.status_code == 200
    return response.json()["status"]


def expire_claim(session: Session, claim: Claim) -> Claim:
    """Moves the lease 60 s into the past and returns the claim with the matching token."""
    claimed_at = session.scalars(
        update(Ticket)
        .where(Ticket.ticket_id == claim.ticket_id)
        .values(claimed_at=func.now() - timedelta(seconds=60))
        .returning(Ticket.claimed_at)
    ).one()
    return replace(claim, claimed_at=claimed_at)


def test_claim_queued_ticket(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)

    claim = claim_ticket(session, ticket_id)

    assert claim is not None
    assert claim.ticket_id == ticket_id
    assert claim.claimed_at is not None
    assert claim.request == TICKET["message"]
    assert get_ticket_status(client, ticket_id) == TicketStatus.TRIAGING


def test_claim_includes_only_enabled_definitions(client: TestClient, session: Session) -> None:
    enabled_id = create_definition(client, "Laptop Request")
    disabled_id = create_definition(client, "Monitor Request")
    assert client.post(f"/api/workflow-definitions/{disabled_id}/disable").status_code == 200
    ticket_id = create_ticket(client)

    claim = claim_ticket(session, ticket_id)

    candidate_ids = [definition.definition_id for definition, _ in claim.candidates]
    assert enabled_id in candidate_ids
    assert disabled_id not in candidate_ids


def test_claim_is_given_once(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    claim_ticket(session, ticket_id)

    # A duplicate delivery of the same message.
    assert claim_ticket(session, ticket_id) is None


def test_claim_cancelled_ticket(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    assert client.post(f"/api/tickets/{ticket_id}/cancel").status_code == 200

    assert claim_ticket(session, ticket_id) is None
    assert get_ticket_status(client, ticket_id) == TicketStatus.CANCELLED


def test_claim_unknown_ticket(session: Session) -> None:
    assert claim_ticket(session, uuid4()) is None


def test_claim_takes_over_expired_lease(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    stale = expire_claim(session, claim_ticket(session, ticket_id))

    claim = claim_ticket(session, ticket_id)

    assert claim is not None
    assert claim.claimed_at > stale.claimed_at
    assert get_ticket_status(client, ticket_id) == TicketStatus.TRIAGING


def test_release_returns_ticket_to_queued(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    claim = claim_ticket(session, ticket_id)

    release_claim(session, claim)

    assert get_ticket_status(client, ticket_id) == TicketStatus.QUEUED
    assert claim_ticket(session, ticket_id) is not None


def test_release_after_takeover_leaves_new_owner(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    stale = expire_claim(session, claim_ticket(session, ticket_id))
    claim_ticket(session, ticket_id)

    # The old owner's token no longer matches, so its release changes nothing.
    release_claim(session, stale)

    assert get_ticket_status(client, ticket_id) == TicketStatus.TRIAGING


def test_release_after_cancel_does_nothing(client: TestClient, session: Session) -> None:
    ticket_id = create_ticket(client)
    claim = claim_ticket(session, ticket_id)
    assert client.post(f"/api/tickets/{ticket_id}/cancel").status_code == 200

    release_claim(session, claim)

    assert get_ticket_status(client, ticket_id) == TicketStatus.CANCELLED


# Scoring. Candidates are built in memory: score_ticket takes no session.


def make_candidate(name: str) -> DefinitionWithVersion:
    definition = WorkflowDefinition(definition_id=uuid4(), name=name, is_enabled=True)
    version = WorkflowDefinitionVersion(
        version_id=uuid4(),
        definition_id=definition.definition_id,
        version_number=1,
        description=f"{name} description",
        confidence_threshold=Decimal("0.80"),
        steps=[],
        required_inputs=[],
        sample_requests=[f"I need a {name}"],
    )
    return definition, version


class FakeProvider:
    """Scores every candidate with one value, unless told to raise, hang or wait at a barrier."""

    def __init__(
        self,
        name: str,
        confidence: str = "0.90",
        error: Exception | None = None,
        hang: bool = False,
        barrier: asyncio.Barrier | None = None,
        results: list[MatchResult] | None = None,
    ) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.confidence = Decimal(confidence)
        self.error = error
        self.hang = hang
        self.barrier = barrier
        self.results = results
        self.calls: list[tuple[str, list[Candidate]]] = []
        self.cancelled = False

    async def score(self, request: str, candidates: list[Candidate]) -> list[MatchResult]:
        self.calls.append((request, candidates))
        try:
            if self.barrier is not None:
                await self.barrier.wait()
            if self.hang:
                await asyncio.Event().wait()
            if self.error is not None:
                # Yield first, so the other provider is mid-call when this one fails.
                await asyncio.sleep(0)
                raise self.error
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.results is not None:
            return self.results
        return [
            MatchResult(version_id=c.version_id, match_confidence=self.confidence)
            for c in candidates
        ]


def score(
    providers: list[FakeProvider],
    candidates: list[DefinitionWithVersion],
    timeout: timedelta = timedelta(seconds=1),
) -> list[ProviderScores]:
    return asyncio.run(score_ticket(providers, TICKET["message"], candidates, timeout))


def test_providers_see_candidates_without_thresholds() -> None:
    definition, version = make_candidate("laptop")
    provider = FakeProvider("anthropic")

    score([provider], [(definition, version)])

    assert provider.calls == [
        (
            TICKET["message"],
            [
                Candidate(
                    version_id=version.version_id,
                    name="laptop",
                    description="laptop description",
                    sample_requests=["I need a laptop"],
                )
            ],
        )
    ]
    assert "confidence_threshold" not in Candidate.model_fields


def test_providers_run_concurrently() -> None:
    # Each provider waits until both have arrived, which can only happen if they run at once.
    async def run() -> list[ProviderScores]:
        barrier = asyncio.Barrier(2)
        providers = [
            FakeProvider("anthropic", barrier=barrier),
            FakeProvider("gemini", barrier=barrier),
        ]
        return await score_ticket(
            providers, TICKET["message"], [make_candidate("laptop")], timedelta(seconds=1)
        )

    results = asyncio.run(run())

    # Each result keeps its own provider's labels, which finish_triage stores with every score.
    assert [(r.provider, r.model) for r in results] == [
        ("anthropic", "anthropic-model"),
        ("gemini", "gemini-model"),
    ]


def test_hung_provider_times_out_and_is_cancelled() -> None:
    hung = FakeProvider("gemini", hang=True)

    with pytest.raises(TimeoutError):
        score([FakeProvider("anthropic"), hung], [make_candidate("laptop")], timedelta(seconds=0.1))

    # The timeout stops the call itself, not just the wait for it.
    assert hung.cancelled


def test_failing_provider_cancels_the_others() -> None:
    hung = FakeProvider("anthropic", hang=True)
    error = RuntimeError("provider unavailable")

    with pytest.RaisesGroup(pytest.RaisesExc(RuntimeError, match="provider unavailable")):
        score([hung, FakeProvider("gemini", error=error)], [make_candidate("laptop")])

    assert hung.cancelled


@pytest.mark.parametrize("shape", ["missing", "unknown", "duplicate"])
def test_invalid_provider_output_is_rejected(shape: str) -> None:
    candidates = [make_candidate("laptop"), make_candidate("monitor")]
    first = candidates[0][1].version_id
    second = candidates[1][1].version_id
    ids = {
        "missing": [first],
        "unknown": [first, second, uuid4()],
        "duplicate": [first, second, second],
    }[shape]
    results = [MatchResult(version_id=i, match_confidence=Decimal("0.50")) for i in ids]

    with pytest.raises(ValueError, match="gemini"):
        score([FakeProvider("anthropic"), FakeProvider("gemini", results=results)], candidates)


def test_no_candidates_calls_no_provider() -> None:
    provider = FakeProvider("anthropic")

    assert score([provider], []) == []
    assert provider.calls == []


@pytest.mark.parametrize("confidence", ["1.5", "-0.1", "1.004"])
def test_match_confidence_outside_range_is_rejected(confidence: str) -> None:
    with pytest.raises(ValidationError):
        MatchResult(version_id=uuid4(), match_confidence=Decimal(confidence))


def test_match_confidence_is_rounded_to_two_places() -> None:
    # The value compared with the threshold must equal the value stored in NUMERIC(3,2).
    result = MatchResult(version_id=uuid4(), match_confidence=Decimal("0.795"))

    assert result.match_confidence == Decimal("0.80")


def test_score_without_providers_is_rejected() -> None:
    # A misconfigured worker must fail loudly, not turn every Ticket UNMATCHED.
    with pytest.raises(ValueError):
        score([], [make_candidate("laptop")])


# Finishing. Scores are built by hand from a real claim's candidates: finish_triage calls no
# provider.


def claim_with_definitions(client: TestClient, session: Session, *names: str) -> Claim:
    for name in names:
        create_definition(client, name)
    claim = claim_ticket(session, create_ticket(client))
    assert claim is not None
    return claim


def version_of(claim: Claim, name: str) -> UUID:
    return next(
        version.version_id for definition, version in claim.candidates if definition.name == name
    )


def scores_for(provider: str, claim: Claim, confidences: dict[str, str]) -> ProviderScores:
    """Scores every candidate: the named ones as given, the rest at 0.10."""
    scores = [
        MatchResult(
            version_id=version.version_id,
            match_confidence=Decimal(confidences.get(definition.name, "0.10")),
        )
        for definition, version in claim.candidates
    ]
    return ProviderScores(provider, f"{provider}-model", scores)


def finish(session: Session, claim: Claim, scores: list[ProviderScores]) -> TicketStatus | None:
    # The savepoint stands in for the worker's transaction, so a failure undoes only this call.
    with session.begin_nested():
        return finish_triage(session, claim, scores)


def get_results(session: Session, ticket_id: UUID) -> list[TriageResult]:
    return list(session.scalars(select(TriageResult).where(TriageResult.ticket_id == ticket_id)))


def get_runs(session: Session, ticket_id: UUID) -> list[WorkflowRun]:
    return list(session.scalars(select(WorkflowRun).where(WorkflowRun.ticket_id == ticket_id)))


def get_attempts(session: Session, ticket_id: UUID) -> int:
    return session.scalar(select(Ticket.triage_attempts).where(Ticket.ticket_id == ticket_id))


def test_agreement_creates_run(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop", "monitor")
    scores = [
        scores_for("anthropic", claim, {"laptop": "0.92"}),
        scores_for("gemini", claim, {"laptop": "0.85"}),
    ]

    assert finish(session, claim, scores) == TicketStatus.TRIAGED

    runs = get_runs(session, claim.ticket_id)
    assert [run.version_id for run in runs] == [version_of(claim, "laptop")]
    assert get_ticket_status(client, claim.ticket_id) == TicketStatus.TRIAGED


def test_disagreement_is_unmatched(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop", "monitor")
    scores = [
        scores_for("anthropic", claim, {"laptop": "0.92"}),
        scores_for("gemini", claim, {"monitor": "0.85"}),
    ]

    assert finish(session, claim, scores) == TicketStatus.UNMATCHED

    assert get_runs(session, claim.ticket_id) == []
    assert get_ticket_status(client, claim.ticket_id) == TicketStatus.UNMATCHED


def test_one_provider_below_threshold_is_unmatched(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop")
    scores = [
        scores_for("anthropic", claim, {"laptop": "0.92"}),
        scores_for("gemini", claim, {"laptop": "0.79"}),
    ]

    assert finish(session, claim, scores) == TicketStatus.UNMATCHED


def test_score_at_threshold_matches(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop")
    scores = [
        scores_for("anthropic", claim, {"laptop": "0.80"}),
        scores_for("gemini", claim, {"laptop": "0.80"}),
    ]

    assert finish(session, claim, scores) == TicketStatus.TRIAGED


def test_tie_within_one_provider_is_unmatched(client: TestClient, session: Session) -> None:
    # The other provider picks laptop, but a tie means this one picked nothing.
    claim = claim_with_definitions(client, session, "laptop", "monitor")
    scores = [
        scores_for("anthropic", claim, {"laptop": "0.90", "monitor": "0.90"}),
        scores_for("gemini", claim, {"laptop": "0.90"}),
    ]

    assert finish(session, claim, scores) == TicketStatus.UNMATCHED


def test_no_scores_is_unmatched(client: TestClient, session: Session) -> None:
    # What score_ticket returns when no definition is enabled.
    claim = claim_with_definitions(client, session)

    assert finish(session, claim, []) == TicketStatus.UNMATCHED
    assert get_attempts(session, claim.ticket_id) == 1


def test_every_score_is_stored(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop", "monitor")
    scores = [
        scores_for("anthropic", claim, {"laptop": "0.92"}),
        scores_for("gemini", claim, {"monitor": "0.85"}),
    ]

    finish(session, claim, scores)

    stored = {
        (r.attempt, r.provider, r.model, r.version_id, r.match_confidence)
        for r in get_results(session, claim.ticket_id)
    }
    assert stored == {
        (1, "anthropic", "anthropic-model", version_of(claim, "laptop"), Decimal("0.92")),
        (1, "anthropic", "anthropic-model", version_of(claim, "monitor"), Decimal("0.10")),
        (1, "gemini", "gemini-model", version_of(claim, "laptop"), Decimal("0.10")),
        (1, "gemini", "gemini-model", version_of(claim, "monitor"), Decimal("0.85")),
    }


def test_second_attempt_is_numbered(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop")
    finish(session, claim, [scores_for("anthropic", claim, {})])
    # Queued again, as clarifying an UNMATCHED Ticket will do.
    session.get(Ticket, claim.ticket_id).status = TicketStatus.QUEUED
    session.flush()
    second = claim_ticket(session, claim.ticket_id)

    finish(session, second, [scores_for("anthropic", second, {})])

    assert sorted(r.attempt for r in get_results(session, claim.ticket_id)) == [1, 2]
    assert get_attempts(session, claim.ticket_id) == 2


def test_run_pins_scored_version_after_publish(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop")
    definition_id = claim.candidates[0][0].definition_id
    # Version 2 raises the threshold above the scores, but the decision uses what was scored.
    content = {k: v for k, v in WORKFLOW_DEFINITION.items() if k != "name"}
    response = client.post(
        f"/api/workflow-definitions/{definition_id}/versions",
        json={**content, "confidence_threshold": "0.99", "base_version": 1},
    )
    assert response.status_code == 201
    scores = [
        scores_for("anthropic", claim, {"laptop": "0.90"}),
        scores_for("gemini", claim, {"laptop": "0.90"}),
    ]

    assert finish(session, claim, scores) == TicketStatus.TRIAGED
    assert [run.version_id for run in get_runs(session, claim.ticket_id)] == [
        version_of(claim, "laptop")
    ]


def test_finish_after_takeover_returns_none(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop")
    stale = expire_claim(session, claim)
    assert claim_ticket(session, claim.ticket_id) is not None
    scores = [scores_for("anthropic", stale, {"laptop": "0.90"})]

    assert finish(session, stale, scores) is None

    assert get_results(session, claim.ticket_id) == []
    assert get_runs(session, claim.ticket_id) == []
    assert get_ticket_status(client, claim.ticket_id) == TicketStatus.TRIAGING


def test_finish_after_cancel_returns_none(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop")
    assert client.post(f"/api/tickets/{claim.ticket_id}/cancel").status_code == 200

    assert finish(session, claim, [scores_for("anthropic", claim, {"laptop": "0.90"})]) is None

    assert get_results(session, claim.ticket_id) == []
    assert get_ticket_status(client, claim.ticket_id) == TicketStatus.CANCELLED


def test_disabled_during_scoring_rolls_back(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop")
    definition_id = claim.candidates[0][0].definition_id
    assert client.post(f"/api/workflow-definitions/{definition_id}/disable").status_code == 200
    scores = [
        scores_for("anthropic", claim, {"laptop": "0.90"}),
        scores_for("gemini", claim, {"laptop": "0.90"}),
    ]

    # ValueError means retry: the worker releases its claim and SQS redelivers.
    with pytest.raises(ValueError):
        finish(session, claim, scores)

    assert get_results(session, claim.ticket_id) == []
    assert get_attempts(session, claim.ticket_id) == 0
    assert get_ticket_status(client, claim.ticket_id) == TicketStatus.TRIAGING


def test_retry_after_disabled_definition_requeues(client: TestClient, session: Session) -> None:
    # The worker's sequence: the failed finish rolls back, then a separate release hands the
    # Ticket back for the redelivery to claim.
    claim = claim_with_definitions(client, session, "laptop")
    definition_id = claim.candidates[0][0].definition_id
    assert client.post(f"/api/workflow-definitions/{definition_id}/disable").status_code == 200
    scores = [
        scores_for("anthropic", claim, {"laptop": "0.90"}),
        scores_for("gemini", claim, {"laptop": "0.90"}),
    ]
    with pytest.raises(ValueError):
        finish(session, claim, scores)

    release_claim(session, claim)

    assert get_ticket_status(client, claim.ticket_id) == TicketStatus.QUEUED
    assert claim_ticket(session, claim.ticket_id) is not None


def test_deleting_unmatched_ticket_deletes_its_scores(client: TestClient, session: Session) -> None:
    claim = claim_with_definitions(client, session, "laptop")
    finish(session, claim, [scores_for("anthropic", claim, {})])
    assert get_results(session, claim.ticket_id) != []

    assert client.delete(f"/api/tickets/{claim.ticket_id}").status_code == 200

    assert get_results(session, claim.ticket_id) == []
