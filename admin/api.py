"""Storage clean-up API (mounted under /api/storage). Same login as the rest of the app (it has one admin sign-in). Nothing here runs by itself."""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import storage

router = APIRouter(prefix="/api/storage")


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except storage.StorageError as e:
        raise HTTPException(400, str(e))


@router.get("")
async def overview():
    return await asyncio.to_thread(storage.overview)


class ClearReq(BaseModel):
    project: str
    mode: str = "folders"                      # folders | older | all
    folders: list[str] = []
    dry_run: bool = True                       # a request that does not say otherwise only measures


@router.post("/clear")
async def clear(body: ClearReq):
    return await asyncio.to_thread(_guard, storage.clear, body.project, body.mode, body.folders, body.dry_run)


class OtherReq(BaseModel):
    key: str
    dry_run: bool = True


@router.post("/other")
async def other(body: OtherReq):
    return await asyncio.to_thread(_guard, storage.clear_other, body.key, body.dry_run)
