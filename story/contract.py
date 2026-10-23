"""The exported data contract (schema version 1.1). Independent of any model or provider: the next module
should depend on this file's shapes only. See docs/story_schema.md."""
from typing import Literal

from pydantic import BaseModel

SCHEMA_VERSION = "1.1"


class SourceRef(BaseModel):
    paragraph_id: int
    page: int | None = None
    section: str = ""
    chapter_index: int | None = None
    chapter_title: str = ""
    locator: str
    text: str = ""


class Person(BaseModel):
    name: str
    role: str = ""


class TimelineEntry(BaseModel):
    when: str = ""
    when_basis: Literal["stated", "inferred", ""] = ""   # stated = the date appears in the cited passages
    what: str
    basis: Literal["quoted", "summarised", "inferred", ""] = ""
    paragraph_ids: list[int] = []


class Claim(BaseModel):
    claim: str
    quote: str = ""
    quote_verified: bool | None = None       # None = no quote given; False = quote not found in cited passages
    support: Literal["strong", "moderate", "weak"] = "moderate"
    basis: Literal["quoted", "summarised", "inferred", ""] = ""   # quoted only when the quote was found verbatim
    paragraph_ids: list[int] = []


class Factor(BaseModel):
    score: float                              # 0-10
    reason: str = ""


class Scores(BaseModel):
    story_score: float                        # 0-100, weighted factors (before manual override)
    evidence_score: float                     # 0-100, kept separate from story appeal
    priority: float                           # 0-100, story_score scaled by evidence_score
    story_score_override: float | None = None
    priority_override: float | None = None
    effective_priority: float
    factors: dict[str, Factor]
    evidence_reason: str = ""
    evidence_breakdown: dict = {}
    completeness: float | None = None         # 0-100, how much of a whole story the evidence holds; separate from evidence_score
    completeness_breakdown: dict = {}


class Flag(BaseModel):
    code: str                                 # nature | gap | stitched | date_no_year | date_inferred | title
    text: str


class Figure(BaseModel):
    id: str
    page: int
    caption: str = ""
    credit: str = ""                          # source credit printed on the page, if any
    rights_flag: bool = False                 # true when the page shows a copyright / permission notice
    file: str = ""                            # path relative to the figures folder of the export, if images are included


class Review(BaseModel):
    status: Literal["pending", "approved", "rejected"]
    needs_research: bool = False
    notes: str = ""
    edited: bool = False


class Related(BaseModel):
    id: str
    title: str = ""
    overlap: float = 0.0


class Lineage(BaseModel):
    origin: str                               # pipeline | merge | split
    merged_from: list[str] = []
    split_from: str | None = None


class StoryRecord(BaseModel):
    id: str
    title: str
    premise: str
    kind: str = ""
    nature: Literal["story", "anecdote", "explainer", "hypothetical", ""] = ""
    curiosity_question: str = ""
    opening_hook: str = ""
    overview: str = ""
    people: list[Person] = []
    chronology: list[TimelineEntry] = []
    conflict: str = ""
    stakes: str = ""
    turning_point: str = ""
    outcome: str = ""
    audience_interest: str = ""
    context_needed: list[str] = []
    claims: list[Claim] = []
    uncertainties: list[str] = []
    research_questions: list[str] = []
    gaps: list[str] = []
    flags: list[Flag] = []
    figures: list[Figure] = []
    scores: Scores
    review: Review
    references: list[SourceRef]
    related: list[Related] = []
    duplicate_warnings: list[Related] = []
    warnings: list[str] = []
    lineage: Lineage


class SourceInfo(BaseModel):
    project_id: str
    title: str
    author: str = ""
    format: str
    url: str = ""
    sha256: str = ""
    pages: int | None = None
    estimated_tokens: int = 0
    chapters: list[dict] = []
    imported_at: str = ""
    overview: str = ""


class ExportDoc(BaseModel):
    schema_version: str = SCHEMA_VERSION
    exported_at: str
    generator: dict
    source: SourceInfo
    filter: dict
    stories: list[StoryRecord]
