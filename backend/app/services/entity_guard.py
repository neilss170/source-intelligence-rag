from app.models.resume import EvidenceUnit
from app.services.routed_retriever import RoutedDenseRetriever
from app.services.tokenization import tokenize

LOOKUP_TRIGGERS = {"completed", "know", "list", "provide", "with"}
ENTITY_STOPWORDS = {
    "a",
    "an",
    "any",
    "completed",
    "course",
    "does",
    "experience",
    "has",
    "have",
    "in",
    "is",
    "know",
    "list",
    "listed",
    "neil",
    "provide",
    "resume",
    "the",
    "their",
    "they",
    "worked",
    "with",
}
STRICT_FACT_TERMS = {
    "address",
    "age",
    "birthday",
    "cgpa",
    "compensation",
    "dob",
    "email",
    "gpa",
    "marital",
    "phone",
    "salary",
}


class EntityGuardRetriever:
    def __init__(
        self,
        retriever: RoutedDenseRetriever,
        evidence: list[EvidenceUnit],
    ) -> None:
        self._retriever = retriever
        self._corpus_terms = set(
            tokenize(
                " ".join(
                    " ".join(
                        [
                            item.title,
                            " ".join(item.technologies),
                            item.text,
                            item.source.source_text,
                        ]
                    )
                    for item in evidence
                )
            )
        )

    def search(self, query: str, *, top_k: int = 5) -> list:
        terms = tokenize(query)
        requested_strict_facts = set(terms) & STRICT_FACT_TERMS
        if requested_strict_facts and not requested_strict_facts.issubset(
            self._corpus_terms
        ):
            return []
        if terms and terms[0] in {"does", "has"} and set(terms) & LOOKUP_TRIGGERS:
            entity_terms = {
                term for term in terms if term not in ENTITY_STOPWORDS and len(term) > 1
            }
            if entity_terms and not entity_terms.issubset(self._corpus_terms):
                return []
        return self._retriever.search(query, top_k=top_k)
