from time import perf_counter

from app.models.query import (
    AnswerMode,
    Citation,
    QueryRequest,
    QueryResponse,
)
from app.services.assistant_router import route_answer_mode
from app.services.citation_validation import validate_citations
from app.services.conversation_context import resolve_follow_up
from app.services.grounded_generator import GroundedGenerator
from app.services.query_classification import classify_query
from app.services.web_search import needs_live_search


class QueryService:
    def __init__(
        self,
        retriever,
        generator: GroundedGenerator,
        general_provider=None,
        web_search_provider=None,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._general_provider = general_provider
        self._web_search_provider = web_search_provider

    def query(self, request: QueryRequest) -> QueryResponse:
        effective_question = resolve_follow_up(request.question, request.history)
        query_type = classify_query(effective_question)
        mode = route_answer_mode(
            effective_question,
            request.scope,
            has_documents=self._retriever is not None,
        )

        if mode is AnswerMode.AMBIGUOUS:
            return _non_workspace_response(
                "Could you be more specific about what you want to know? "
                "Mention the document, topic, metric, or time period you mean.",
                mode,
                query_type,
            )
        if mode is AnswerMode.EMPTY_WORKSPACE:
            return _non_workspace_response(
                "There are no documents in this workspace yet. Upload a PDF, "
                "TXT, Markdown, CSV, JSON, Excel, or DOCX file, then ask a "
                "question about its contents.",
                mode,
                query_type,
            )
        if mode is AnswerMode.UNSUPPORTED_ANALYSIS:
            return _non_workspace_response(
                "The indexed files do not contain a supported structured table "
                "for that calculation. Upload a CSV, JSON, or Excel dataset "
                "with the required columns and try again.",
                mode,
                query_type,
            )
        if mode is AnswerMode.GENERAL:
            return _general_response(
                request,
                query_type,
                self._general_provider,
                self._web_search_provider,
                retrieval_ms=0,
            )

        retrieval_started = perf_counter()
        hits = self._retriever.search(
            effective_question,
            top_k=request.top_k,
        )
        retrieval_ms = round((perf_counter() - retrieval_started) * 1000)

        if (
            request.scope.value == "auto"
            and not _has_document_anchor(effective_question, hits)
            and self._general_provider
        ):
            return _general_response(
                request,
                query_type,
                self._general_provider,
                self._web_search_provider,
                retrieval_ms=retrieval_ms,
            )

        generation_started = perf_counter()
        generated = self._generator.generate(
            effective_question,
            hits,
            query_type,
        )
        generation_ms = round((perf_counter() - generation_started) * 1000)

        if (
            generated.insufficient_evidence
            and request.scope.value == "auto"
            and not _has_document_anchor(effective_question, hits)
            and self._general_provider
        ):
            return _general_response(
                request,
                query_type,
                self._general_provider,
                self._web_search_provider,
                retrieval_ms=retrieval_ms,
            )

        retrieved_ids = {hit.evidence.evidence_id for hit in hits}
        validate_citations(generated, retrieved_ids)
        if generated.insufficient_evidence:
            return QueryResponse(
                answer=generated.answer,
                citations=[],
                grounded=False,
                groundedness_score=0.0,
                query_type=query_type,
                retrieval_ms=retrieval_ms,
                generation_ms=generation_ms,
                mode=AnswerMode.WORKSPACE,
            )
        citations = [
            Citation(
                evidence_id=hit.evidence.evidence_id,
                section=hit.evidence.section,
                title=hit.evidence.title,
                filename=hit.evidence.source.filename,
                page=hit.evidence.source.page,
                excerpt=hit.evidence.source.source_text,
                relevance=max(0.0, min(1.0, float(hit.score))),
            )
            for hit in hits
            if hit.evidence.evidence_id in generated.evidence_ids
        ]
        return QueryResponse(
            answer=generated.answer,
            citations=citations,
            grounded=True,
            groundedness_score=1.0,
            query_type=query_type,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            mode=AnswerMode.WORKSPACE,
        )


def _non_workspace_response(
    answer: str,
    mode: AnswerMode,
    query_type,
) -> QueryResponse:
    return QueryResponse(
        answer=answer,
        citations=[],
        grounded=False,
        groundedness_score=0.0,
        query_type=query_type,
        retrieval_ms=0,
        generation_ms=0,
        mode=mode,
    )


def _general_response(
    request: QueryRequest,
    query_type,
    provider,
    web_search_provider,
    *,
    retrieval_ms: int,
) -> QueryResponse:
    started = perf_counter()
    if (
        web_search_provider
        and web_search_provider.configured
        and needs_live_search(request.question)
    ):
        search_answer = web_search_provider.search(request.question)
        if search_answer:
            return QueryResponse(
                answer=search_answer.answer,
                citations=[],
                web_sources=search_answer.sources,
                grounded=True,
                groundedness_score=1.0,
                query_type=query_type,
                retrieval_ms=retrieval_ms,
                generation_ms=round((perf_counter() - started) * 1000),
                mode=AnswerMode.GENERAL,
            )
    answer = provider.answer(request.question, request.history)
    return QueryResponse(
        answer=answer,
        citations=[],
        grounded=False,
        groundedness_score=0.0,
        query_type=query_type,
        retrieval_ms=retrieval_ms,
        generation_ms=round((perf_counter() - started) * 1000),
        mode=AnswerMode.GENERAL,
    )


def _has_document_anchor(question: str, hits: list) -> bool:
    from app.services.tokenization import tokenize

    ignored = {
        "a",
        "an",
        "are",
        "did",
        "do",
        "does",
        "have",
        "how",
        "is",
        "it",
        "of",
        "the",
        "their",
        "they",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
    }
    question_terms = {
        term for term in tokenize(question) if term not in ignored and len(term) > 2
    }
    if not question_terms:
        return False
    evidence_terms = {
        term
        for hit in hits
        for term in tokenize(
            " ".join(
                [
                    hit.evidence.title,
                    hit.evidence.organization or "",
                    hit.evidence.text,
                ]
            )
        )
    }
    return bool(question_terms & evidence_terms)
