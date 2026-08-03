from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.core.dependencies import get_query_service
from app.main import app
from app.models.query import QueryResponse, QueryType


@dataclass
class StubQueryService:
    def query(self, request) -> QueryResponse:
        return QueryResponse(
            answer="The resume does not cover that information.",
            citations=[],
            grounded=True,
            groundedness_score=1.0,
            query_type=QueryType.SKILL,
            retrieval_ms=1,
            generation_ms=0,
        )


def test_query_endpoint_uses_typed_contract() -> None:
    app.dependency_overrides[get_query_service] = lambda: StubQueryService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/query",
                json={"question": "Does Neil know React?"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["grounded"] is True
    assert response.json()["citations"] == []
