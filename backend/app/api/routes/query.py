from fastapi import APIRouter, Depends

from app.core.dependencies import get_query_service
from app.models.query import QueryRequest, QueryResponse
from app.services.query_service import QueryService

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(
    request: QueryRequest,
    service: QueryService = Depends(get_query_service),
) -> QueryResponse:
    return service.query(request)
