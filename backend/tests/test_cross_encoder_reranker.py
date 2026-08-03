from dataclasses import dataclass

from app.models.resume import EvidenceUnit, ResumeSection, SourceReference
from app.services.cross_encoder_reranker import CrossEncoderReranker


@dataclass(frozen=True)
class Hit:
    evidence: EvidenceUnit
    score: float


class Retriever:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query, *, top_k=5):
        return self.hits[:top_k]


class Scorer:
    def predict(self, pairs):
        return [0.1, 0.9]


def _evidence(identifier: str, text: str) -> EvidenceUnit:
    return EvidenceUnit(
        evidence_id=identifier,
        section=ResumeSection.DOCUMENT,
        title="Guide",
        text=text,
        source=SourceReference(
            document_id="doc_guide",
            filename="guide.txt",
            page=1,
            source_text=text,
        ),
    )


def test_cross_encoder_reorders_dense_candidates() -> None:
    first = _evidence("ev_guide_first", "A broad but weak match.")
    second = _evidence("ev_guide_second", "The directly relevant answer.")
    reranker = CrossEncoderReranker(
        Retriever([Hit(first, 0.8), Hit(second, 0.7)]),
        scorer=Scorer(),
    )

    hits = reranker.search("What is the direct answer?", top_k=2)

    assert [hit.evidence.evidence_id for hit in hits] == [
        "ev_guide_second",
        "ev_guide_first",
    ]
