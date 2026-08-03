from app.models.query import ChatMessage, ChatRole
from app.services.tokenization import tokenize

ELLIPTICAL_PHRASES = {
    "and them",
    "any others",
    "give examples",
    "give me a few",
    "give me some",
    "how about them",
    "more examples",
    "name a few",
    "name some",
    "tell me more",
    "what about it",
    "what about them",
}
VAGUE_TERMS = {
    "few",
    "it",
    "more",
    "ones",
    "other",
    "others",
    "some",
    "that",
    "them",
    "these",
    "they",
    "those",
}


def resolve_follow_up(question: str, history: list[ChatMessage]) -> str:
    normalized = " ".join(question.lower().strip(" ?.!").split())
    terms = set(tokenize(question))
    is_short = len(terms) <= 6
    is_elliptical = normalized in ELLIPTICAL_PHRASES or (
        is_short and bool(terms & VAGUE_TERMS)
    )
    if not is_elliptical:
        return question

    previous_user_question = next(
        (
            message.content
            for message in reversed(history)
            if message.role is ChatRole.USER and message.content.strip()
        ),
        None,
    )
    if not previous_user_question:
        return question
    return f"Previous topic: {previous_user_question}\nFollow-up: {question}"
