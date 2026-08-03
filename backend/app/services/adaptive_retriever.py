from app.services.tokenization import tokenize

SYNTHESIS_TERMS = {
    "challenge",
    "describe",
    "example",
    "strongest",
}


class AdaptiveTopKRetriever:
    def __init__(self, retriever) -> None:
        self._retriever = retriever

    def search(self, query: str, *, top_k: int = 3) -> list:
        terms = set(tokenize(query))
        is_synthesis = bool(terms & SYNTHESIS_TERMS) or (
            "how" in terms and "project" in terms
        )
        if terms & {"language", "languages"}:
            selected_top_k = 3
        elif terms & {"school", "studied", "study", "studying"}:
            selected_top_k = 2
        else:
            selected_top_k = 4 if is_synthesis else 1
        return self._retriever.search(query, top_k=selected_top_k)
