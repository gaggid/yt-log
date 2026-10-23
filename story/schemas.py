"""Pydantic models for model output. Lenient about harmless variations (P12, "12", ranges, nulls),
strict about required content. Validation failures trigger a bounded retry; nothing is invented to fill gaps."""
import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def _ids(v):
    if v is None:
        return []
    if isinstance(v, (int, str)):
        v = [v]
    out: list[int] = []
    for x in v:
        if isinstance(x, bool):
            continue
        if isinstance(x, int):
            out.append(x)
        elif isinstance(x, str):
            for m in re.finditer(r"(\d+)(?:\s*[-–]\s*P?(\d+))?", x):
                a, b = int(m.group(1)), m.group(2)
                if b and 0 < int(b) - a <= 60:
                    out.extend(range(a, int(b) + 1))
                else:
                    out.append(a)
                    if b:
                        out.append(int(b))
    return list(dict.fromkeys(out))


# Paragraph labels are citation keys only: "[P12]", "[P12, P14]", "(P12)" must never leak into prose fields.
_TAG = re.compile(r"\s*[\[(]\s*P\d+(?:\s*(?:[,;–-]|and)?\s*P?\d+)*\s*[\])]")


def strip_tags(t: str) -> str:
    return re.sub(r"\s{2,}", " ", _TAG.sub("", t)).strip()


def _str(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return strip_tags("; ".join(str(x) for x in v))
    return strip_tags(str(v))


def _strs(v):
    if v is None:
        return []
    if isinstance(v, str):
        v = strip_tags(v)
        return [v] if v else []
    return [s for s in (_str(x) for x in v) if s]


def _num(v):
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        if not m:
            raise ValueError(f"not a number: {v!r}")
        v = float(m.group())
    return v


ParaIds = Annotated[list[int], BeforeValidator(_ids)]
Str = Annotated[str, BeforeValidator(_str)]
StrList = Annotated[list[str], BeforeValidator(_strs)]


class M(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ── chunk analysis ──────────────────────────────────────────────────────────

NATURES = ("story", "anecdote", "explainer", "hypothetical")


def _nature(v):
    v = _str(v).lower().replace(" ", "_").replace("-", "_")
    alias = {"case_study": "story", "narrative": "story", "example": "anecdote", "illustration": "explainer",
             "lesson": "explainer", "tutorial": "explainer", "scenario": "hypothetical", "hypothetical_example": "hypothetical"}
    v = alias.get(v, v)
    return v if v in NATURES else ""


def _basis(v):
    v = _str(v).lower()
    return v if v in ("quoted", "summarised", "inferred") else ""


def _when_basis(v):
    v = _str(v).lower()
    return v if v in ("stated", "inferred") else ""


Nature = Annotated[str, BeforeValidator(_nature)]
Basis = Annotated[str, BeforeValidator(_basis)]
WhenBasis = Annotated[str, BeforeValidator(_when_basis)]


class Event(M):
    what: Str
    when: Str = ""
    when_basis: WhenBasis = ""
    who: StrList = []
    para_ids: ParaIds = []


class Entity(M):
    name: Str
    role: Str = ""
    para_ids: ParaIds = []


class Fact(M):
    claim: Str
    caveat: Str = ""
    para_ids: ParaIds = []


class Seed(M):
    title: Str
    premise: Str = ""
    para_ids: ParaIds = []


class ChunkAnalysis(M):
    summary: Str
    events: list[Event] = []
    entities: list[Entity] = []
    facts: list[Fact] = []
    open_questions: StrList = []
    story_seeds: list[Seed] = []

    @field_validator("summary")
    @classmethod
    def _summary(cls, v):
        if len(v) < 20:
            raise ValueError("summary is missing or too short")
        return v


# ── roll-ups ────────────────────────────────────────────────────────────────

class ChapterRollup(M):
    summary: Str
    themes: StrList = []
    threads: StrList = []

    @field_validator("summary")
    @classmethod
    def _summary(cls, v):
        if len(v) < 20:
            raise ValueError("summary is missing or too short")
        return v


class Thread(M):
    title: Str
    description: Str = ""
    chapter_idxs: ParaIds = []
    para_ids: ParaIds = []


class BookIndex(M):
    overview: Str
    themes: StrList = []
    threads: list[Thread] = []

    @field_validator("overview")
    @classmethod
    def _overview(cls, v):
        if len(v) < 20:
            raise ValueError("overview is missing or too short")
        return v


# ── discovery ───────────────────────────────────────────────────────────────

KINDS = ("incident", "multi_passage", "multi_chapter", "case_study", "surprising_fact", "decision_sequence")


def _kind(v):
    v = _str(v).lower().replace(" ", "_").replace("-", "_")
    return v if v in KINDS else "incident"


class Stub(M):
    title: Str
    premise: Str
    why: Str = ""
    nature: Nature = ""
    kind: Annotated[str, BeforeValidator(_kind)] = "incident"
    potential: Annotated[float, BeforeValidator(_num)] = 5
    para_ids: ParaIds = []

    @field_validator("title", "premise")
    @classmethod
    def _need(cls, v):
        if not v:
            raise ValueError("title and premise are required")
        return v

    @field_validator("potential")
    @classmethod
    def _pot(cls, v):
        return max(0.0, min(10.0, v))


class Discovery(M):
    candidates: list[Stub] = []


# ── story draft ─────────────────────────────────────────────────────────────

class Factor(M):
    score: Annotated[float, BeforeValidator(_num)]
    reason: Str = ""

    @field_validator("score")
    @classmethod
    def _clamp(cls, v):
        return max(0.0, min(10.0, float(v)))


class Scores(M):
    hook: Factor
    narrative: Factor
    payoff: Factor
    emotion: Factor
    standalone: Factor


def _support(v):
    v = _str(v).lower()
    return v if v in ("strong", "moderate", "weak") else "moderate"


class Claim(M):
    claim: Str
    basis: Basis = ""
    quote: Str = ""
    para_ids: ParaIds = []
    support: Annotated[str, BeforeValidator(_support)] = "moderate"


class Person(M):
    name: Str
    role: Str = ""


class TimelineEntry(M):
    when: Str = ""
    when_basis: WhenBasis = ""
    what: Str
    basis: Basis = ""
    para_ids: ParaIds = []


class DraftOut(M):
    title: Str
    premise: Str
    nature: Nature = ""
    curiosity_question: Str = ""
    opening_hook: Str = ""
    overview: Str
    people: list[Person] = []
    chronology: list[TimelineEntry] = []
    conflict: Str = ""
    stakes: Str = ""
    turning_point: Str = ""
    outcome: Str = ""
    audience_interest: Str = ""
    context_needed: StrList = []
    claims: list[Claim] = Field(default_factory=list)
    uncertainties: StrList = []
    gaps: StrList = []
    title_flags: StrList = []
    research_questions: StrList = []
    scores: Scores
    evidence: Factor

    @field_validator("title", "premise", "overview")
    @classmethod
    def _need(cls, v):
        if not v:
            raise ValueError("title, premise and overview are required")
        return v

    @field_validator("claims")
    @classmethod
    def _claims(cls, v):
        if not v:
            raise ValueError("at least one claim with its evidence is required")
        return v
