from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.core.dependencies import (
    get_ingestion_service,
    get_query_service,
)
from app.models.document import DocumentResponse, DocumentStatus
from app.services.document_ingestion import (
    DocumentIngestionError,
    DocumentIngestionService,
)
from app.services.uploaded_evidence_repository import UploadedEvidenceRepository

router = APIRouter(tags=["documents"])


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents() -> list[DocumentResponse]:
    settings = get_settings()
    uploaded = UploadedEvidenceRepository(
        settings.index_dir / "uploaded_evidence.json"
    ).load()
    grouped: dict[str, list] = {}
    for evidence in uploaded:
        grouped.setdefault(evidence.source.document_id, []).append(evidence)
    return [
        DocumentResponse(
            document_id=document_id,
            filename=items[0].source.filename,
            status=DocumentStatus.READY,
            evidence_count=len(items),
        )
        for document_id, items in grouped.items()
    ]


@router.post(
    "/documents",
    response_model=list[DocumentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_documents(
    files: list[UploadFile] = File(...),
    service: DocumentIngestionService = Depends(get_ingestion_service),
) -> list[DocumentResponse]:
    if not files:
        raise HTTPException(status_code=400, detail="Select at least one document.")

    results: list[DocumentResponse] = []
    for file in files:
        try:
            results.append(
                service.ingest(
                    file.filename or "document",
                    await file.read(),
                )
            )
        except DocumentIngestionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    get_query_service.cache_clear()
    return results


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    service: DocumentIngestionService = Depends(get_ingestion_service),
) -> None:
    if not service.delete(document_id):
        raise HTTPException(status_code=404, detail="The document was not found.")
    get_query_service.cache_clear()
