from time import perf_counter

from app.models.query import (
    AnswerMode,
    Citation,
    QueryRequest,
    QueryResponse,
)
from app.services.assistant_router import route_answer_mode
from app.services.bm25_retriever import ScoredEvidence
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
        *,
        verifier=None,
        min_top_k: int = 0,
    ) -> None:
        """Create the service.

        Args:
            verifier: Checks each cited sentence against its passages; its
                score becomes the response's ``groundedness_score``.
            min_top_k: Passages retrieved at least, whatever the request asks
                for - a model answering from one passage cannot compare two.
        """
        self._retriever = retriever
        self._generator = generator
        self._general_provider = general_provider
        self._web_search_provider = web_search_provider
        self._verifier = verifier
        self._min_top_k = min_top_k

    def query(self, request: QueryRequest) -> QueryResponse:
        rewrite = getattr(self._generator, "rewrite_question", None)
        effective_question = (
            rewrite(request.question, request.history)
            if rewrite
            else resolve_follow_up(request.question, request.history)
        )
        writes_with_model = getattr(self._generator, "writes_with_model", False)
        query_type = classify_query(effective_question)
        mode = route_answer_mode(
            effective_question,
            request.scope,
            has_documents=self._retriever is not None,
        )
        if writes_with_model and mode in (
            AnswerMode.AMBIGUOUS,
            AnswerMode.UNSUPPORTED_ANALYSIS,
        ):
            # The model reads the documents and can ask for clarification or
            # count rows itself; the keyword rules would only refuse.
            mode = AnswerMode.WORKSPACE

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
        whole_workspace = getattr(self._generator, "whole_workspace", None)
        hits = whole_workspace(effective_question) if whole_workspace else None
        if hits is None:
            hits = self._retriever.search(
                effective_question,
                top_k=max(request.top_k, self._min_top_k),
            )
        retrieval_ms = round((perf_counter() - retrieval_started) * 1000)

        if (
            request.scope.value == "auto"
            and not writes_with_model
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
            history=request.history,
        )
        generation_ms = round((perf_counter() - generation_started) * 1000)

        if generated.abstained:
            # A document question the passages do not answer. Saying so is
            # the answer; handing it to general chat would invite a guess.
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

        if generated.from_model and generated.insufficient_evidence:
            # The model judged this is not answerable from the documents and
            # answered it as such - small talk, a question about the assistant,
            # general knowledge, or "the documents do not cover that".
            if (
                request.scope.value == "auto"
                and self._web_search_provider
                and self._web_search_provider.configured
                and needs_live_search(request.question)
            ):
                return _general_response(
                    request,
                    query_type,
                    self._general_provider,
                    self._web_search_provider,
                    retrieval_ms=retrieval_ms,
                )
            return QueryResponse(
                answer=generated.answer,
                citations=[],
                grounded=False,
                groundedness_score=0.0,
                query_type=query_type,
                retrieval_ms=retrieval_ms,
                generation_ms=generation_ms,
                mode=(
                    AnswerMode.WORKSPACE
                    if request.scope.value == "workspace"
                    else AnswerMode.GENERAL
                ),
            )

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

        # SQL results the model ran while answering are citable passages too.
        hits = [
            *hits,
            *(ScoredEvidence(evidence, 1.0) for evidence in generated.extra_evidence),
        ]
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
        # In cited order, so citation n is the one behind the answer's [n].
        hits_by_id = {hit.evidence.evidence_id: hit for hit in hits}
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
            for hit in (
                hits_by_id[evidence_id] for evidence_id in generated.evidence_ids
            )
        ]
        groundedness, unsupported = 1.0, []
        if self._verifier is not None:
            verifying_started = perf_counter()
            cited = {
                number: hits_by_id[evidence_id].evidence
                for number, evidence_id in enumerate(generated.evidence_ids, 1)
                if _is_prose(hits_by_id[evidence_id].evidence)
            }
            report = self._verifier.verify(
                generated.answer,
                {number: evidence.text for number, evidence in cited.items()},
                # The section path, without the file name in front of it.
                {
                    number: evidence.title.split(" > ", 1)[-1]
                    for number, evidence in cited.items()
                },
            )
            generation_ms += round((perf_counter() - verifying_started) * 1000)
            if report.checked:
                groundedness, unsupported = report.score, report.unsupported
        return QueryResponse(
            answer=generated.answer,
            citations=citations,
            grounded=True,
            groundedness_score=groundedness,
            unsupported_claims=unsupported,
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


#: Sources whose passages are records ("destination: Paris"), not sentences.
_RECORD_EXTENSIONS = (".csv", ".json", ".xlsx")


def _is_prose(evidence) -> bool:
    """Whether an NLI model can judge claims against this passage."""
    return not (
        evidence.evidence_id.startswith("ev_sql_")
        or evidence.source.filename.lower().endswith(_RECORD_EXTENSIONS)
    )
