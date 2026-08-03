from app.models.query import GeneratedAnswer


class UnsupportedCitationError(ValueError):
    """Raised when generated output cites evidence outside retrieved context."""


def validate_citations(
    answer: GeneratedAnswer,
    retrieved_evidence_ids: set[str],
) -> None:
    unsupported = set(answer.evidence_ids) - retrieved_evidence_ids
    if unsupported:
        raise UnsupportedCitationError(
            f"Generated answer cited unsupported evidence: {sorted(unsupported)}"
        )
