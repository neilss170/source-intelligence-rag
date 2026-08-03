from app.models.resume import ResumeSection
from app.services.dense_retriever import DenseRetriever, DenseScoredEvidence
from app.services.query_router import route_sections
from app.services.tokenization import tokenize


class RoutedDenseRetriever:
    def __init__(self, dense: DenseRetriever) -> None:
        self._dense = dense

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> list[DenseScoredEvidence]:
        routed_sections = route_sections(query)
        sections = routed_sections
        if sections is not None:
            sections = sections | {ResumeSection.DOCUMENT}
        candidate_k = 8 if routed_sections == {ResumeSection.EDUCATION} else top_k
        hits = self._dense.search(
            query,
            top_k=candidate_k,
            sections=sections,
        )
        if routed_sections == {ResumeSection.EDUCATION}:
            hits = rank_education_hits(query, hits)
        return hits[:top_k]


def rank_education_hits(
    query: str,
    hits: list[DenseScoredEvidence],
) -> list[DenseScoredEvidence]:
    terms = set(tokenize(query))

    def priority(hit: DenseScoredEvidence) -> tuple[int, float]:
        title = hit.evidence.title.lower()
        organization = (hit.evidence.organization or "").lower()
        if terms & {"college", "degree", "graduate", "graduation", "university"}:
            preferred = (
                "bachelor" in title
                or "college" in organization
                or "university" in organization
            )
        elif "school" in terms:
            preferred = (
                "secondary" in title or "school" in organization
            ) and "bachelor" not in title
        else:
            preferred = False
        return (0 if preferred else 1, -hit.score)

    return sorted(hits, key=priority)
