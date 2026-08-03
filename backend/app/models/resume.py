from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResumeSection(StrEnum):
    DOCUMENT = "document"
    SUMMARY = "summary"
    EDUCATION = "education"
    EXPERIENCE = "experience"
    PROJECTS = "projects"
    SKILLS = "skills"
    CERTIFICATIONS = "certifications"
    EXTRACURRICULAR = "extracurricular"


class DateRange(BaseModel):
    start: date | None = None
    end: date | None = None
    label: str | None = None


class SourceReference(BaseModel):
    document_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    source_text: str = Field(min_length=1)


class Achievement(BaseModel):
    text: str = Field(min_length=1)
    technologies: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    source: SourceReference

    @field_validator("technologies", "metrics")
    @classmethod
    def remove_blank_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class EducationEntry(BaseModel):
    institution: str = Field(min_length=1)
    qualification: str = Field(min_length=1)
    field_of_study: str | None = None
    period: DateRange = Field(default_factory=DateRange)
    grade: str | None = None
    details: list[str] = Field(default_factory=list)
    source: SourceReference


class ExperienceEntry(BaseModel):
    organization: str = Field(min_length=1)
    role: str = Field(min_length=1)
    location: str | None = None
    period: DateRange = Field(default_factory=DateRange)
    achievements: list[Achievement] = Field(default_factory=list)
    source: SourceReference


class ProjectEntry(BaseModel):
    name: str = Field(min_length=1)
    summary: str | None = None
    period: DateRange = Field(default_factory=DateRange)
    technologies: list[str] = Field(default_factory=list)
    achievements: list[Achievement] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    source: SourceReference


class CertificationEntry(BaseModel):
    name: str = Field(min_length=1)
    issuer: str | None = None
    issued: date | None = None
    source: SourceReference


class CandidateResume(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_name: str = Field(min_length=1)
    professional_summary: str | None = None
    education: list[EducationEntry] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class EvidenceUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^ev_[a-z0-9_]+$")
    section: ResumeSection
    title: str = Field(min_length=1)
    organization: str | None = None
    period: DateRange = Field(default_factory=DateRange)
    technologies: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)
    source: SourceReference
