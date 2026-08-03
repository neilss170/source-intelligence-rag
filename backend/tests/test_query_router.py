from app.models.resume import ResumeSection
from app.services.query_router import route_sections


def test_routes_education_question() -> None:
    assert route_sections("When will Neil graduate?") == {ResumeSection.EDUCATION}
    assert route_sections("Where have they studied?") == {ResumeSection.EDUCATION}


def test_routes_project_question() -> None:
    assert route_sections("Which project used K-Means?") == {ResumeSection.PROJECTS}


def test_routes_internship_question_to_empty_supported_section() -> None:
    assert route_sections("What internships has Neil completed?") == {
        ResumeSection.EXPERIENCE
    }


def test_leaves_ambiguous_question_unfiltered() -> None:
    assert route_sections("Tell me about Neil") is None
