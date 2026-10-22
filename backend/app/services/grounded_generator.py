import re
from dataclasses import dataclass

from app.models.query import GeneratedAnswer, QueryType
from app.services.answer_intent import AnswerIntent, detect_answer_intent
from app.services.bm25_retriever import ScoredEvidence
from app.services.tokenization import tokenize

INSUFFICIENT_ANSWER = (
    "I don't have that information in the uploaded documents.\n\n"
    "The retrieved content does not provide evidence for this question, so I "
    "won't guess or use unrelated details. Upload a relevant source if you want "
    "this included."
)
QUESTION_STOPWORDS = {
    "a",
    "an",
    "any",
    "candidate",
    "completed",
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
GENERIC_TITLE_TERMS = {
    "controlled",
    "intelligent",
    "model",
    "project",
    "real-time",
    "system",
}
DISPLAY_NAMES = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "gpa": "GPA",
    "react": "React",
}
EDUCATION_INTENT_TERMS = {
    "college",
    "education",
    "school",
    "studied",
    "study",
    "studying",
    "university",
}
INSTITUTION_PATTERN = re.compile(
    r"\b("
    r"(?:(?:[A-Z](?:\.[A-Z])+\.?|[A-Z][A-Za-z&'-]+)\s+){0,4}"
    r"(?:College|University|School|Institute)"
    r"(?:\s+(?:of\s+)?(?:[A-Z][A-Za-z&'-]*|[A-Z]{2,}))?"
    r"(?:,\s*[A-Z][A-Za-z.'-]+)?"
    r")\b"
)


@dataclass(frozen=True, slots=True)
class GroundedGenerator:
    max_evidence: int = 4

    def generate(
        self,
        question: str,
        hits: list[ScoredEvidence],
        query_type: QueryType,
        history=(),
    ) -> GeneratedAnswer:
        question_terms = tokenize(question)
        answer_intent = detect_answer_intent(question)
        is_yes_no = answer_intent is AnswerIntent.YES_NO
        if not hits:
            subject = _requested_subject(question_terms)
            return GeneratedAnswer(
                answer=(
                    f"No — {subject} is not mentioned in the indexed documents."
                    "\n\n"
                    "I can only confirm information supported by the available "
                    "sources, so I won't claim experience or details that are "
                    "not documented."
                    if is_yes_no
                    else INSUFFICIENT_ANSWER
                ),
                insufficient_evidence=True,
            )

        terms = set(question_terms)
        selected = hits[: self.max_evidence]
        primary = selected[0].evidence
        title_identifiers = set(tokenize(primary.title)) - GENERIC_TITLE_TERMS
        if "project" in terms and terms & title_identifiers:
            selected = [hit for hit in selected if hit.evidence.title == primary.title]

        if terms & EDUCATION_INTENT_TERMS:
            institutions = _extract_institutions(
                [hit.evidence.text for hit in selected]
            )
            if institutions:
                answer = _format_education_answer(institutions)
            elif primary.organization:
                answer = (
                    f"They studied at {primary.organization}."
                    "\n\n"
                    f"The indexed education record lists {primary.title}"
                    f"{_period_suffix(primary.period.label)}."
                )
            else:
                answer = INSUFFICIENT_ANSWER
        elif is_yes_no and not _question_subject_is_supported(question, selected):
            answer = INSUFFICIENT_ANSWER
        elif is_yes_no:
            subject = _requested_subject(question_terms)
            answer = (
                f"Yes — the indexed documents provide evidence for {subject}."
                "\n\n"
                f"{_direct_evidence_sentence(primary.title, primary.text)}"
            )
        elif terms & {"degree", "qualification"}:
            answer = (
                f"Neil is pursuing {primary.title}."
                "\n\n"
                f"The education entry is from {primary.organization or 'the resume'}"
                f"{_period_suffix(primary.period.label)}."
            )
        elif "school" in terms and len(selected) > 1:
            school_entries = [
                hit.evidence for hit in selected if hit.evidence.organization
            ]
            organizations = list(
                dict.fromkeys(
                    entry.organization for entry in school_entries if entry.organization
                )
            )
            answer = (
                f"Neil completed his secondary education at "
                f"{_human_list(organizations)}."
                "\n\n"
                "The indexed records list "
                + "; ".join(
                    f"{entry.title}{_period_suffix(entry.period.label)}"
                    for entry in school_entries
                )
                + "."
            )
        elif terms & {"college", "school", "university"} and primary.organization:
            answer = (
                f"Neil attends {primary.organization}."
                "\n\n"
                f"The indexed education record lists {primary.title}"
                f"{_period_suffix(primary.period.label)}."
            )
        elif terms & {"graduate", "graduation", "when"} and primary.period.label:
            answer = (
                f"Neil's degree is listed for {primary.period.label}."
                "\n\n"
                "The documents do not provide a more specific graduation date, "
                "so this answer is limited to the recorded study period."
            )
        elif terms & {
            "language",
            "languages",
            "algorithm",
            "algorithms",
            "technologies",
        }:
            values = list(primary.technologies)
            if terms & {"language", "languages"}:
                values.extend(
                    _extract_programming_languages(
                        [hit.evidence.text for hit in selected]
                    )
                )
                values = list(dict.fromkeys(values))
            answer = (
                f"The indexed documents list {_human_list(values)}."
                if values
                else INSUFFICIENT_ANSWER
            )
        elif "which" in terms and "project" in terms:
            answer = (
                f"The relevant project is {primary.title}."
                "\n\n"
                f"{_ensure_sentence(primary.text)}"
            )
        elif query_type is QueryType.EVALUATIVE:
            answer = (
                "A hiring decision requires broader assessment than the indexed "
                "documents alone can provide."
                "\n\n"
                "The verified sources show: "
                + " ".join(_ensure_sentence(hit.evidence.text) for hit in selected)
            )
        elif query_type is QueryType.BEHAVIORAL:
            answer = f"A documented example comes from {primary.title}.\n\n" + " ".join(
                _ensure_sentence(hit.evidence.text) for hit in selected
            )
        elif answer_intent is AnswerIntent.SUMMARY and len(selected) > 1:
            answer = (
                f"The strongest matching evidence comes from {primary.title}."
                "\n\n"
                + " ".join(_ensure_sentence(hit.evidence.text) for hit in selected)
            )
        elif answer_intent is AnswerIntent.EXPLANATION:
            answer = _focused_explanation(
                question,
                [hit.evidence.text for hit in selected],
            )
        else:
            answer = _focused_evidence_answer(question, primary.text)
        insufficient = answer == INSUFFICIENT_ANSWER
        return GeneratedAnswer(
            answer=answer,
            evidence_ids=(
                [] if insufficient else [hit.evidence.evidence_id for hit in selected]
            ),
            insufficient_evidence=insufficient,
        )


def _ensure_sentence(text: str) -> str:
    cleaned = text.strip()
    return cleaned if cleaned.endswith((".", "!", "?")) else f"{cleaned}."


def _direct_evidence_sentence(title: str, text: str) -> str:
    return f"In the {title} entry, {_lower_first(_ensure_sentence(text))}"


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _requested_subject(question_terms: list[str]) -> str:
    subject = [
        term
        for term in question_terms
        if term not in QUESTION_STOPWORDS and len(term) > 1
    ]
    return (
        " ".join(DISPLAY_NAMES.get(term, term) for term in subject)
        if subject
        else "that"
    )


def _human_list(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _period_suffix(period: str | None) -> str:
    return f", covering {period}" if period else ""


def _extract_institutions(texts: list[str]) -> list[str]:
    institutions: list[str] = []
    for text in texts:
        for match in INSTITUTION_PATTERN.finditer(text):
            institution = re.sub(r"\s+", " ", match.group(1)).strip(" ,.")
            if institution and institution not in institutions:
                institutions.append(institution)
    return institutions


def _format_education_answer(institutions: list[str]) -> str:
    colleges = [
        name
        for name in institutions
        if "college" in name.lower() or "university" in name.lower()
    ]
    schools = [name for name in institutions if "school" in name.lower()]
    lines: list[str] = []
    if colleges:
        lines.append(f"College: {_human_list(colleges)}")
    if schools:
        lines.append(f"School: {_human_list(schools)}")
    if not lines:
        return f"They studied at {_human_list(institutions)}."
    return "They studied at the following institutions:\n\n" + "\n".join(lines)


def _focused_evidence_answer(question: str, text: str) -> str:
    question_terms = {
        term
        for term in _lexical_terms(question)
        if term not in QUESTION_STOPWORDS and len(term) > 2
    }
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
        if sentence.strip()
    ]
    if not sentences:
        return INSUFFICIENT_ANSWER

    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (
            -len(question_terms & _lexical_terms(item[1])),
            item[0],
        ),
    )
    best = ranked[0][1]
    if question_terms and not (question_terms & _lexical_terms(best)):
        return INSUFFICIENT_ANSWER
    if len(best) > 320:
        best = best[:317].rsplit(" ", 1)[0] + "..."
    return _ensure_sentence(best)


def _lexical_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for term in re.findall(r"[a-z0-9]+", text.lower()):
        terms.add(term)
        if len(term) > 3 and term.endswith("s"):
            terms.add(term[:-1])
    return terms


def _question_subject_is_supported(question: str, selected: list) -> bool:
    ignored = QUESTION_STOPWORDS | {
        "are",
        "can",
        "could",
        "did",
        "do",
        "does",
        "would",
        "you",
        "maybe",
        "name",
        "few",
        "links",
        "link",
    }
    subject_terms = {
        term
        for term in _lexical_terms(question)
        if term not in ignored and len(term) > 2
    }
    if not subject_terms:
        return False
    evidence_terms = {
        term
        for hit in selected
        for term in _lexical_terms(
            " ".join(
                [
                    hit.evidence.title,
                    hit.evidence.organization or "",
                    hit.evidence.text,
                ]
            )
        )
    }
    return bool(subject_terms & evidence_terms)


def _extract_programming_languages(texts: list[str]) -> list[str]:
    languages: list[str] = []
    for text in texts:
        match = re.search(
            r"\bProgramming\s*:\s*(.+?)"
            r"(?=\s+(?:Machine Learning|Web Technologies|Skills|"
            r"Projects|Certifications|Extracurricular)\s*:?\s*|$)",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        for value in re.split(r",|/|\band\b", match.group(1)):
            cleaned = value.strip(" .•-")
            if cleaned and len(cleaned.split()) <= 3 and cleaned not in languages:
                languages.append(cleaned)
    return languages


def _focused_explanation(question: str, texts: list[str]) -> str:
    question_terms = {
        term
        for term in _lexical_terms(question)
        if term not in QUESTION_STOPWORDS
        and term not in {"describe", "explain", "project"}
        and len(term) > 2
    }
    segments: list[str] = []
    for text in texts:
        segments.extend(
            segment.strip()
            for segment in re.split(r"\s*[•]\s*|(?<=[.!?])\s+|\n+", text)
            if segment.strip()
        )
    scored = [
        (index, len(question_terms & _lexical_terms(segment)), segment)
        for index, segment in enumerate(segments)
    ]
    matching = [item for item in scored if item[1] > 0]
    if not matching:
        return INSUFFICIENT_ANSWER
    best_index, _, best_segment = max(matching, key=lambda item: (item[1], -item[0]))
    best_segment = _trim_segment_to_query(best_segment, question_terms)

    chosen: list[str] = []
    if len(best_segment) <= 360:
        chosen.append(best_segment)
    if best_index + 1 < len(segments) and len(segments[best_index + 1]) <= 260:
        chosen.append(segments[best_index + 1])
    if not chosen:
        return _focused_evidence_answer(question, best_segment)
    return " ".join(_ensure_sentence(segment) for segment in chosen[:2])


def _trim_segment_to_query(segment: str, question_terms: set[str]) -> str:
    lowered = segment.lower()
    positions = [
        lowered.find(term) for term in question_terms if lowered.find(term) >= 0
    ]
    if not positions:
        return segment
    first_match = min(positions)
    if first_match < 80:
        return segment
    return segment[first_match:].lstrip(" ,:;-")
