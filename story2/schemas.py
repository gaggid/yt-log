"""Model-output schemas for Phase 2 (lenient about harmless variations, strict about required content)."""
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from story import schemas as s1
from . import svara

STRUCTURES = ("cold_open", "mystery", "decision_consequence", "problem_mechanism", "myth_correction", "multi_case",
              "question_journey")


def _structure(v):
    v = s1._str(v).lower().replace(" ", "_").replace("-", "_")
    alias = {"cold_open_context_escalation_reveal_consequence": "cold_open", "decision": "decision_consequence",
             "mystery_clues_resolution": "mystery", "problem": "problem_mechanism", "myth": "myth_correction",
             "multiple_cases": "multi_case", "question": "question_journey", "educational": "question_journey"}
    v = alias.get(v, v)
    return v if v in STRUCTURES else "cold_open"


def _emotion(v):
    return svara.norm_emotion(v)


def _secs(v):
    try:
        return max(0.0, min(svara.MAX_PAUSE_S, float(s1._num(v))))
    except (TypeError, ValueError):
        return 0.0


Str, StrList = s1.Str, s1.StrList


class M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Beat(M):
    id: Str = ""
    name: Str = ""                      # opening, context, escalation, turning_point, payoff, ending ...
    purpose: Str
    takeaway: Str = ""                  # what the viewer should understand or feel after this beat
    facts: StrList = []                 # which facts of the story it uses, in our words


class Blueprint(M):
    structure: Annotated[str, BeforeValidator(_structure)] = "cold_open"
    why_structure: Str = ""
    viewer_promise: Str
    central_question: Str = ""
    opening: Str = ""
    context: Str = ""
    conflict: Str = ""
    turning_point: Str = ""
    payoff: Str = ""
    ending: Str = ""
    beats: list[Beat] = []

    @field_validator("beats")
    @classmethod
    def _beats(cls, v):
        if len(v) < 3:
            raise ValueError("a blueprint needs at least three beats")
        return v


class Sentence(M):
    text: Str
    emotion: Annotated[str, BeforeValidator(_emotion)] = "neutral"
    pause_after_s: Annotated[float, BeforeValidator(_secs)] = 0.0

    @field_validator("text")
    @classmethod
    def _t(cls, v):
        if not v:
            raise ValueError("empty sentence")
        return v


class Pronounce(M):
    word: Str
    say: Str = ""
    note: Str = ""


class SegmentOut(M):
    beat: Str = ""
    sentences: list[Sentence] = Field(default_factory=list)
    emphasis: StrList = []
    pronounce: list[Pronounce] = []
    facts_used: StrList = []

    @field_validator("sentences")
    @classmethod
    def _s(cls, v):
        if not v:
            raise ValueError("a segment needs at least one sentence")
        return v


class NarrationOut(M):
    segments: list[SegmentOut]

    @field_validator("segments")
    @classmethod
    def _seg(cls, v):
        if not v:
            raise ValueError("no narration segments")
        return v
