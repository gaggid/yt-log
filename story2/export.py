"""Batch D: the versioned JSON export. One document that later media modules can read without reinterpreting the story or redoing editorial
decisions. `public` carries everything that may be spoken, shown or sent to a model. `evidence` carries the fact-checking trail and never reaches
a prompt. Before a document is returned, the public part is scanned for anything that points back to the source; a finding blocks the export."""
import hashlib
import json
import re
from pathlib import Path

import config
from jsonschema import Draft202012Validator

from story import db

from . import editorial, imgprompts, leak, planner, providers, store, storyboard
from .export_schema import SCHEMA, SCHEMA_ID, SCHEMA_VERSION


class ExportError(Exception):
    pass


UNSET = "(not set yet)"
TTS_NOTES = {
    "engine": "svara-tts", "recommended_request": {"response_format": "wav", "seed": 7, "temperature": 0.6, "repetition_penalty": 1.25},
    "input": "send each segment's `annotated` field as the text; emotion tags and [pause] tags are already in Svara's syntax",
    "chunking": "one segment per request; the gateway splits long text at sentence ends and crossfades. Generation ran about 3.7 times slower than real time on the "
                "test machine (a 43 second part took about 160 seconds), so the gateway's svara-tts `timeout_s` must be at least 600 (its default is 120)",
    "measured_pace_wpm": 148, "script": "Hinglish: Hindi in Devanagari with English words in Latin script, numbers spelled as words",
    "emotion_policy": "one steady emotion per segment; at most one change, at a real turn. Mixing emotions inside a request shifts pace and voice audibly",
    "voice": "hi_male is the only male Hindi voice Svara offers; it has no style or depth options, and its pitch cannot be changed",
    "known_gap": "narrator avatar and name are not decided yet"}
IMAGE_NOTES = {
    "defaults": "send size and prompt; leave steps, cfg, sampler and scheduler to the gateway's tuned defaults",
    "references": "edits accept at most 3 reference images and no masks; write edits as 'change X, keep Y'",
    "text_in_images": "never ask an image model for charts, documents, screens or exact figures; scenes with feasibility.level == needs_asset get a backdrop only, "
                      "and `prompts.*.overlay` says what a later deterministic step must draw",
    "negative_prompt": "send `negative_prompt` only for models whose provider entry says negative_prompt is true",
}
PUBLISHING_CHECKLIST = [
    "Facts independently verified against public sources",
    "Working title renamed (it must not echo the source)",
    "Rights for any real person, brand or third-party material checked by a person",
    "Image model licence: owner decision recorded (open-source models, not a blocker); re-check if the use changes",
    "Narration listened to in the final voice",
]


def _strings(x, path=""):
    if isinstance(x, str):
        yield path, x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _strings(v, f"{path}.{k}" if path else k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _strings(v, f"{path}[{i}]")


def leak_scan(public: dict, prof: leak.SourceProfile, title: str) -> dict:
    """Everything in `public` that a viewer or a model could see or hear, checked for pointers to the source and for copied wording."""
    findings = []
    skip = ("image_models.providers", "production_notes")
    for path, text in _strings(public):
        if any(path.startswith(s) for s in skip) or len(text.split()) < 2:
            continue
        for f in leak.check(text, prof, scene=not path.startswith("narration")):
            findings.append({"where": path, **f.as_dict()})
    for f in leak.check(title, prof):
        findings.append({"where": "plan.working_title", **f.as_dict()})
    return {"ok": not findings, "findings": findings[:50]}


def _public_scene(sc: dict, plan: dict) -> dict:
    d = {k: v for k, v in sc["data"].items() if k not in ("evidence_ids", "adapters", "model", "previews", "correction")}
    out = {"id": sc["id"], "seq": sc["seq"], "segment_id": sc["segment_id"], "sentence_range": [sc["s_from"], sc["s_to"]], "start_s": sc["start_s"], "end_s": sc["end_s"],
           "duration_s": sc["duration_s"], "status": sc["status"], "locked": sc["locked"], **d,
           "image_model": providers.model_for(sc["data"], plan["settings"])}
    out["previews"] = [{"id": p["id"], "file": p["file"], "model": p["model"], "seed": p.get("seed"), "rating": p.get("rating", {}),
                        "matches_current_prompt": p.get("source_hash") == ((sc["data"].get("prompts") or {}).get(p["adapter"]) or {}).get("source_hash")}
                       for p in sc["data"].get("previews", [])]
    return out


def _providers_public(plan: dict) -> dict:
    lic = providers.settings_for(plan["settings"])["licence_checks"]
    out = {}
    for mid in providers.IMAGE_MODELS:
        m = providers.get(mid)
        out[mid] = {"label": m["label"], "adapter": m["adapter"], "adapter_version": m["adapter_version"], "variant": m["variant"], "negative_prompt": m["negative_prompt"],
                    "edits": m["edits"], "max_references": m["max_references"], "masks": m["masks"], "reliable_text": m["reliable_text"], "steps": m["steps"], "cfg": m["cfg"],
                    "max_pixels": m["max_pixels"], "prompt_enhancer": m["prompt_enhancer"],
                    "licence": {"status": m["licence"]["status"], "note": m["licence"]["note"], "confirmed_by_person": bool(lic.get(mid)),
                                "owner_override": bool(lic.get(mid)), "owner_decision": "open-source models; licence is not treated as a blocker (owner, 2026-10-24)"}}
    return out


def build(plan_id: str, refresh: bool = True, export_rev: int = 0) -> dict:
    """Assemble and validate the document. `refresh` re-runs every automatic check so the reports and scores inside it describe this exact content."""
    so = editorial.signoff(plan_id) if refresh else None
    plan = planner.get_plan(plan_id)
    if not plan["blueprint"] or not plan["segments"] or not plan["scenes"]:
        raise ExportError("nothing to export yet: plan the story, write the narration and design the storyboard first")
    story = planner._story_for(plan)
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    ev, pub = story["evidence"], story["public"]
    beats = plan["blueprint"]["beats"]
    names = {b["id"]: b["name"] for b in beats}
    try:                                                                  # real voice files, when Phase 3 has made them
        from story3 import store as media
        voice_id = plan["narrator"].get("voice") or "hi_male"
        audio = {s["id"]: media.chosen_voice(plan_id, s, voice_id) for s in plan["segments"]}
    except Exception:  # noqa: BLE001 - an export must never fail because media is missing
        audio = {}
    segs = sorted(plan["segments"], key=lambda s: (s["seq"], s["id"]))
    scenes = sorted(plan["scenes"], key=lambda s: (s["start_s"], s["seq"]))
    ap = editorial.approval_state(plan)
    scores = (so or {}).get("scores") or (plan["validation"] or {}).get("scores") or editorial.score(plan_id)
    narr = dict(plan["validation"] or {})
    storyboard_rep, prompts_rep = narr.pop("storyboard", None) or {}, narr.pop("prompts", None) or {}
    narr.pop("scores", None)
    blueprint = json.loads(json.dumps(plan["blueprint"]))
    beat_facts = {b["id"]: b.pop("facts", []) for b in blueprint["beats"]}          # which facts a beat leans on is the evidence trail, not public text
    narrator = {k: v for k, v in plan["narrator"].items()}
    narrator["name"] = narrator.get("name") or ""
    public = {
        "narrator": narrator,
        "blueprint": blueprint,
        "narration": {"segments": [
            {"id": s["id"], "seq": s["seq"], "beat": s["beat"], "beat_name": names.get(s["beat"], ""), "plain": s["plain"], "annotated": s["annotated"],
             "sentences": [{"n": i, **x} for i, x in enumerate(s["sentences"], 1)], "emphasis": s["emphasis"], "pronounce": s["pronounce"],
             "duration_s": s["duration_s"], "scene_ids": [sc["id"] for sc in scenes if sc["segment_id"] == s["id"]], "status": s["status"], "locked": s["locked"],
             **({"audio": {"file": audio[s["id"]]["file"], "duration_s": audio[s["id"]]["meta"]["duration_s"], "attempt": audio[s["id"]]["attempt"],
                           "approved": audio[s["id"]]["approved"], "voice": audio[s["id"]]["meta"].get("voice")}} if audio.get(s["id"]) else {})}
            for s in segs]},
        "scenes": [_public_scene(sc, plan) for sc in scenes],
        "assets": [{"id": a["id"], "kind": a["kind"], "name": a["name"], "description": a["data"].get("description", ""), "fixed": a["data"].get("fixed", []),
                    "flexible": a["data"].get("flexible", []), "period": a["data"].get("period", ""), "fictionalisation": a["data"].get("fictionalisation", "generic_reconstruction"),
                    "reference_images": a["data"].get("reference_images", []), "locked": a["locked"]} for a in plan["assets"]],
        "image_models": {"default": providers.settings_for(plan["settings"])["default"], "by_type": providers.settings_for(plan["settings"])["by_type"], "providers": _providers_public(plan)},
        "production_notes": {"tts": {**TTS_NOTES, "voice_id": narrator.get("voice") or "hi_male"}, "images": IMAGE_NOTES,
                             "scenes_needing_built_graphics": [sc["id"] for sc in scenes if sc["data"]["feasibility"]["level"] == "needs_asset"]},
    }
    title = ev["working_title"]
    gate = leak_scan(public, prof, title)
    if not gate["ok"]:
        raise ExportError("the public part still points back to the source or copies it: " + "; ".join(f"{f['where']}: {f['kind']} “{f['text']}”" for f in gate["findings"][:5]))
    evidence = {
        "story": {"candidate_id": ev["candidate_id"], "project_id": ev["project_id"], "paragraph_ids": ev["paragraph_ids"], "pages": ev["pages"],
                  "claims": ev["claims"], "flags": ev["flags"], "scores": ev["scores"],
                  "figures": [{k: f.get(k) for k in ("id", "page", "rights_flag") if f.get(k) is not None} for f in ev["figures"]]},
        "segments": {s["id"]: {"evidence_ids": s["evidence_ids"], "facts_used": s["facts_used"]} for s in segs},
        "scenes": {sc["id"]: {"evidence_ids": sc["data"].get("evidence_ids", []), "facts_fixed": (sc["data"].get("facts") or {}).get("fixed", [])} for sc in scenes},
        "assets": {a["id"]: {"evidence_note": a["data"].get("evidence_note", "")} for a in plan["assets"]},
        "blueprint_facts": beat_facts,
        "research_gaps": [*pub["gaps"], *pub["uncertainties"]],
        "publishing_checklist": [{"item": t, "done": t.startswith("Image model licence")} for t in PUBLISHING_CHECKLIST],
    }
    blockers = [b["text"] for b in (so["blockers"] if so else [])]
    if ap["state"] == "draft":
        blockers.append("The plan is not approved yet.")
    elif ap["state"] == "changed":
        blockers.append("The plan changed after it was approved; approve it again.")
    warns = [w["text"] for w in (so["warnings"] if so else [])]
    revs = editorial.history(plan_id, 30)
    doc = {
        "schema": SCHEMA_ID, "schema_version": SCHEMA_VERSION, "generated_at": db.now(),
        "generator": {"app": "source-to-story", "phase": 2, "adapters": {a: providers.get(m)["adapter_version"] for a, m in (("qwen", "qwen-image-2.1"), ("flux", "flux2-klein-9b"))}},
        "plan": {"id": plan["id"], "project_id": plan["project_id"], "story_id": plan["candidate_id"], "format": plan["format"], "target_minutes": plan["settings"]["minutes"],
                 "duration_s": plan["duration_s"], "content_hash": editorial.content_hash(plan), "working_title": title, "title_is_working": True,
                 "story_nature": story["candidate"]["nature"] or "", "verification": plan["verification"], "export_rev": export_rev, "language": "hi-Deva+Latn"},
        "approval": {k: v for k, v in ap.items() if k in ("state", "at", "note", "warnings", "content_hash")},
        "ready_for_generation": {"ok": not blockers, "blockers": blockers, "warnings": warns},
        "public": public, "evidence": evidence,
        "validation": {"narration": narr, "storyboard": storyboard_rep, "prompts": prompts_rep, "public_leak_check": gate, "scores": scores},
        "revisions": {"count": len(editorial.history(plan_id, 100000)), "recent": [{"ts": r["ts"], "what": r["what"], "detail": r["detail"]} for r in revs]},
    }
    errs = sorted(Draft202012Validator(SCHEMA).iter_errors(doc), key=lambda e: list(e.path))
    if errs:
        raise ExportError("the export does not match its schema: " + "; ".join(f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message[:120]}" for e in errs[:5]))
    return doc


# ── saved exports ───────────────────────────────────────────────────────────

def export_dir(plan_id: str):
    d = config.DATA_DIR / "plan_exports" / plan_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_exports(plan_id: str) -> list[dict]:
    out = []
    for f in sorted(export_dir(plan_id).glob("video-plan_*.json")):
        m = re.search(r"_v(\d+)_([0-9a-f]{8})\.json$", f.name)
        if not m:
            continue
        with open(f, encoding="utf-8") as fh:
            head = fh.read(20000)                       # the fields below sit at the top of the file; no need to parse a large document on every poll
        ch = re.search(r'"content_hash":\s*"([0-9a-f]+)"', head)
        ok = re.search(r'"ready_for_generation":\s*\{\s*"ok":\s*(true|false)', head)
        st = re.search(r'"approval":\s*\{\s*"state":\s*"(\w+)"', head)
        out.append({"rev": int(m.group(1)), "file": f.name, "bytes": f.stat().st_size, "created_at": f.stat().st_mtime, "content_hash": ch.group(1) if ch else None,
                    "ready": bool(ok and ok.group(1) == "true"), "approval": st.group(1) if st else None, "path": str(f)})
    return sorted(out, key=lambda x: -x["rev"])


def save(plan_id: str) -> dict:
    """Build, validate and write the next numbered export. Older exports are kept; the numbers only go up."""
    existing = list_exports(plan_id)
    rev = (existing[0]["rev"] if existing else 0) + 1
    doc = build(plan_id, True, rev)
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = export_dir(plan_id) / f"video-plan_{plan_id}_v{rev:03d}_{sha[:8]}.json"
    path.write_text(text, encoding="utf-8")
    store.log(plan_id, "export", {"rev": rev, "file": path.name, "sha256": sha, "ready": doc["ready_for_generation"]["ok"], "approval": doc["approval"]["state"]})
    return {"rev": rev, "file": path.name, "path": str(path), "bytes": len(text.encode("utf-8")), "sha256": sha, "ready_for_generation": doc["ready_for_generation"],
            "approval": doc["approval"]["state"], "content_hash": doc["plan"]["content_hash"]}


def write_schema_file() -> str:
    p = Path(__file__).resolve().parent.parent / "docs" / "plan_schema.json"
    p.write_text(json.dumps(SCHEMA, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(p)
