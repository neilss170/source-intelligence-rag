from app.models.resume import ResumeSection
from app.services.tokenization import tokenize

EDUCATION_TERMS = {
    "college",
    "degree",
    "education",
    "graduate",
    "graduation",
    "gpa",
    "school",
    "studied",
    "study",
    "studying",
    "university",
}
CERTIFICATION_TERMS = {"certification", "certifications", "certificate", "course"}
EXTRACURRICULAR_TERMS = {
    "community",
    "extracurricular",
    "leadership",
    "rotaract",
    "volunteer",
}
EXPERIENCE_TERMS = {
    "employment",
    "experience",
    "intern",
    "internship",
    "internships",
    "job",
    "role",
}
PROJECT_TERMS = {
    "built",
    "example",
    "flask",
    "k-means",
    "project",
    "projects",
    "sensor",
    "system",
}
SKILL_TERMS = {
    "algorithm",
    "algorithms",
    "fastapi",
    "language",
    "languages",
    "react",
    "skill",
    "skills",
    "technologies",
}


def route_sections(question: str) -> set[ResumeSection] | None:
    terms = set(tokenize(question))
    if terms & EDUCATION_TERMS:
        return {ResumeSection.EDUCATION}
    if terms & CERTIFICATION_TERMS:
        return {ResumeSection.CERTIFICATIONS}
    if terms & EXTRACURRICULAR_TERMS:
        return {ResumeSection.EXTRACURRICULAR}
    if terms & EXPERIENCE_TERMS:
        return {ResumeSection.EXPERIENCE}
    if terms & PROJECT_TERMS:
        return {ResumeSection.PROJECTS}
    if terms & SKILL_TERMS:
        return {ResumeSection.SKILLS, ResumeSection.PROJECTS}
    if "hire" in terms:
        return {ResumeSection.SUMMARY}
    return None
