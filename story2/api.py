"""HTTP API for Phase 2 (mounted under /api/plans). Same login as the rest of the app."""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from story import llm, settings as settings_mod
from story.llm import LLMError
from . import intake, planner

router = APIRouter(prefix="/api/plans")
_busy: set[str] = set()


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (planner.PlanError, intake.IntakeError) as e:
        raise HTTPException(400, str(e))


class NewPlan(BaseModel):
    candidate_id: str
    narrator_name: str = ""
    minutes: float = planner.DEFAULT_MINUTES
    allow_unapproved: bool = False


@router.get("")
async def plans(candidate_id: str = ""):
    return planner.list_plans(candidate_id)


@router.post("")
async def new_plan(body: NewPlan):
    return _guard(planner.create_plan, body.candidate_id, body.narrator_name, body.minutes, body.allow_unapproved)


@router.get("/{plan_id}")
async def plan(plan_id: str):
    return _guard(planner.get_plan, plan_id)


class Narrator(BaseModel):
    name: str | None = None
    voice: str | None = None
    gender: str | None = None


@router.patch("/{plan_id}/narrator")
async def narrator(plan_id: str, body: Narrator):
    return _guard(planner.set_narrator, plan_id, body.name, **{k: v for k, v in body.model_dump().items() if k != "name" and v})


async def _run(plan_id: str, fn, *a):
    if plan_id in _busy:
        raise HTTPException(409, "this plan is already being written")
    _busy.add(plan_id)
    try:
        s = settings_mod.get()
        backend = llm.ChatBackend(s, settings_mod.api_key())
        return await fn(plan_id, backend, s, *a)
    except planner.PlanError as e:
        raise HTTPException(400, str(e))
    except LLMError as e:
        raise HTTPException(502, f"the model could not complete this step: {e}")
    finally:
        _busy.discard(plan_id)


@router.post("/{plan_id}/blueprint")
async def blueprint(plan_id: str):
    return await _run(plan_id, planner.make_blueprint)


class NarrationReq(BaseModel):
    beat_ids: list[str] | None = None


@router.post("/{plan_id}/narration")
async def narration(plan_id: str, body: NarrationReq | None = None):
    return await _run(plan_id, planner.make_narration, (body.beat_ids if body else None))


class SegmentPatch(BaseModel):
    text: str | None = None
    sentences: list[dict] | None = None
    status: str | None = None
    locked: bool | None = None
    emphasis: list[str] | None = None
    pronounce: list[dict] | None = None


@router.patch("/segments/{seg_id}")
async def patch_segment(seg_id: str, body: SegmentPatch):
    f = {k: v for k, v in body.model_dump().items() if k not in ("text", "sentences") and v is not None}
    return _guard(planner.edit_segment, seg_id, body.sentences, body.text, **f)


@router.post("/{plan_id}/validate")
async def validate(plan_id: str):
    return await asyncio.to_thread(_guard, planner.validate_plan, plan_id)
