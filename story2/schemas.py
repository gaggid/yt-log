"""Model-output schemas for Phase 2 (lenient about harmless variations, strict about required content)."""
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from story import schemas as s1
from . import maya, svara

STRUCTURES = ("cold_open", "mystery", "decision_consequence", "problem_mechanism", "myth_correction", "multi_case",
              "question_journey", "life_arc", "evidence_case", "numbered_list")


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
    reveal: Str = ""                    # the one thing this beat lets the viewer learn (the answer to a question opened earlier)
    hold_back: Str = ""                 # what this beat deliberately does NOT say yet, and the beat where it will be told
    plant: Str = ""                     # a small detail told here that pays off later (empty if none)
    feeling: Str = ""                   # the one feeling of this beat: fear, sad, anger, happy or neutral
    ends_on: Str = ""                   # the question, promise or ticking clock this beat ends on, so the viewer needs the next beat
    chapter_title: Str = ""             # YouTube chapter title: curiosity-gap, 5-8 words, no spoilers
    retention_hook: Str = ""            # re-engagement moment for the 60-90s retention pulse in this beat
    primary_visual: Str = ""            # what the camera MUST show in this beat — the concept or object itself, not a character reacting to it
    unfilmable: StrList = []            # concepts in this beat that cannot be directly filmed (invisible, microscopic, cosmic, statistical)
    visual_device: Str = ""             # for each item in unfilmable, the decided visual representation (empty if nothing is unfilmable)


class Blueprint(M):
    structure: Annotated[str, BeforeValidator(_structure)] = "cold_open"
    why_structure: Str = ""
    viewer_promise: Str
    central_question: Str = ""
    cold_open: Str = ""                 # the single most striking moment, shown first, before any background
    hook_scene_brief: Str = ""          # the concrete camera image for seconds 0-5: what is on screen before any context
    cold_open_visual: Str = ""          # what the camera shows before context is established — the thing, place or action
    next_hook: Str = ""                 # one sentence the narrator says at the end to plant the next video
    series_placement: Str = ""          # series name + 2-3 related story premises this could belong to
    music_brief: Str = ""               # overall mood + 2-3 moments where music shifts
    indian_hook: Str = ""               # what specifically resonates with Indian youth about this story
    stakes: Str = ""                    # who or what is at risk, and the clock if there is one
    false_answer: Str = ""              # the obvious explanation the story first leans on, which turns out wrong (empty if none)
    dark_moment: Str = ""               # the point where it looks lost, just before the turn (empty if none)
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
    tag: Annotated[str, BeforeValidator(maya.norm_tag)] = ""            # Maya voice tag; the storyboard fills it, narration does not
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
