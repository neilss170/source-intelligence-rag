from enum import StrEnum

from app.services.tokenization import tokenize


class AnswerIntent(StrEnum):
    YES_NO = "yes_no"
    WHERE = "where"
    WHEN = "when"
    WHO = "who"
    LIST = "list"
    SUMMARY = "summary"
    EXPLANATION = "explanation"
    FACT = "fact"


YES_NO_STARTERS = {
    "are",
    "can",
    "did",
    "do",
    "does",
    "has",
    "have",
    "is",
    "was",
    "were",
}
LIST_TERMS = {"list", "which", "what"}
SUMMARY_TERMS = {"overview", "summarize", "summary"}
EXPLANATION_TERMS = {"describe", "explain", "how", "why"}


def detect_answer_intent(question: str) -> AnswerIntent:
    terms = tokenize(question)
    if not terms:
        return AnswerIntent.FACT
    first = terms[0]
    if first in YES_NO_STARTERS:
        return AnswerIntent.YES_NO
    if first == "where":
        return AnswerIntent.WHERE
    if first == "when":
        return AnswerIntent.WHEN
    if first == "who":
        return AnswerIntent.WHO
    if set(terms) & SUMMARY_TERMS:
        return AnswerIntent.SUMMARY
    if first in EXPLANATION_TERMS or set(terms) & EXPLANATION_TERMS:
        return AnswerIntent.EXPLANATION
    if first in LIST_TERMS or "list" in terms:
        return AnswerIntent.LIST
    return AnswerIntent.FACT
