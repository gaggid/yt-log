"""JSON Schema (2020-12) for the exported video plan. This is the contract future media modules (image, voice, video, editing) read, so it names
exactly what must be present. Unknown extra fields are allowed so the contract can grow without breaking readers; `schema_version` follows
semantic versioning (a breaking change bumps the major number)."""

SCHEMA_ID = "source-to-story/video-plan"
SCHEMA_VERSION = "1.0.0"

_STR = {"type": "string"}
_NUM = {"type": "number"}
_INT = {"type": "integer"}
_STRS = {"type": "array", "items": _STR}
_OBJ = {"type": "object"}


def _obj(required: list[str], props: dict, extra: bool = True) -> dict:
    return {"type": "object", "required": required, "properties": props, "additionalProperties": extra}


SENTENCE = _obj(["n", "text", "emotion", "pause_after_s"], {
    "n": _INT, "text": _STR, "emotion": {"enum": ["neutral", "happy", "sad", "anger", "fear", "clear"]}, "pause_after_s": {"type": "number", "minimum": 0, "maximum": 10}})

SEGMENT = _obj(["id", "seq", "beat", "plain", "annotated", "sentences", "duration_s", "scene_ids", "status"], {
    "id": _STR, "seq": _NUM, "beat": _STR, "beat_name": _STR, "plain": _STR, "annotated": _STR, "sentences": {"type": "array", "items": SENTENCE, "minItems": 1},
    "emphasis": _STRS, "pronounce": {"type": "array", "items": _OBJ}, "duration_s": {"type": "number", "minimum": 0}, "scene_ids": _STRS,
    "status": {"enum": ["draft", "edited", "approved", "rejected"]}, "locked": {"type": "boolean"},
    "audio": _obj(["file", "duration_s"], {"file": _STR, "duration_s": {"type": "number", "minimum": 0}, "attempt": _INT, "approved": {"type": "boolean"}, "voice": _STR})})

PROMPT = _obj(["adapter", "model", "adapter_version", "mode", "prompt", "negative_prompt", "size", "params", "references", "source_hash"], {
    "adapter": {"enum": ["qwen", "flux"]}, "model": _STR, "adapter_version": _STR,
    "mode": {"enum": ["generate", "edit", "overlay_plate"]}, "prompt": {"type": "string", "minLength": 1}, "negative_prompt": _STR,
    "size": _obj(["width", "height"], {"width": _INT, "height": _INT}), "params": _OBJ,
    "references": {"type": "array", "maxItems": 3, "items": _OBJ}, "missing_references": {"type": "array", "items": _OBJ}, "notes": _STRS,
    "edit_instruction": _STR, "overlay": _OBJ, "source_hash": _STR})

SCENE = _obj(["id", "seq", "segment_id", "sentence_range", "start_s", "end_s", "duration_s", "status", "narrative", "visual_type", "subject", "action",
              "setting", "composition", "lighting", "output", "feasibility", "generation_intent", "image_model", "prompts"], {
    "id": _STR, "seq": _NUM, "segment_id": _STR,
    "sentence_range": {"type": "array", "items": _INT, "minItems": 2, "maxItems": 2},
    "start_s": {"type": "number", "minimum": 0}, "end_s": {"type": "number", "minimum": 0}, "duration_s": {"type": "number", "minimum": 0},
    "status": {"enum": ["draft", "edited", "approved", "rejected"]}, "locked": {"type": "boolean"},
    "narrative": _obj(["purpose"], {"purpose": _STR, "new_information": _STR, "takeaway": _STR, "emotional_effect": _STR}),
    "visual_type": _STR, "subject": _STR, "action": _STR, "setting": _OBJ, "composition": _OBJ, "lighting": _STR, "palette": _STR, "atmosphere": _STR, "style": _STR,
    "layers": _OBJ, "motion_intent": _STR, "text_on_screen": {"type": "array", "items": _OBJ}, "facts": _OBJ,
    "continuity": _obj(["assets"], {"assets": _STRS, "unknown": _STRS}),
    "output": _obj(["aspect_ratio", "width", "height"], {"aspect_ratio": {"enum": ["16:9", "9:16"]}, "width": _INT, "height": _INT}),
    "exclusions": _STRS,
    "feasibility": _obj(["level"], {"level": {"enum": ["ok", "needs_asset"]}, "needs_asset": _STR, "fallback": _STR, "notes": _STR}),
    "generation_intent": _STR, "image_model": _STR,
    "prompts": _obj(["qwen", "flux"], {"qwen": PROMPT, "flux": PROMPT}), "previews": {"type": "array", "items": _OBJ}})

ASSET = _obj(["id", "kind", "name", "description", "fictionalisation"], {
    "id": _STR, "kind": {"enum": ["person", "place", "prop", "style", "narrator"]}, "name": _STR, "description": _STR, "fixed": _STRS, "flexible": _STRS,
    "period": _STR, "fictionalisation": _STR, "reference_images": {"type": "array", "items": _OBJ}, "locked": {"type": "boolean"}})

DIMENSION = _obj(["key", "label", "score", "band", "reason", "fixes"], {
    "key": _STR, "label": _STR, "score": {"type": "integer", "minimum": 0, "maximum": 100}, "band": {"enum": ["good", "ok", "weak"]}, "reason": _STR,
    "fixes": {"type": "array", "items": _obj(["text"], {"text": _STR, "where": _STRS, "tab": _STR})}, "measured": _OBJ})

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": f"https://example.invalid/{SCHEMA_ID}/{SCHEMA_VERSION}",
    "title": "Source-to-Story video plan",
    "description": "Narration, storyboard and model-aware image prompts for one approved story. `public` holds everything that may be spoken, shown or sent to "
                   "a media model. `evidence` is internal fact-checking data and must never be rendered, spoken or put in a prompt.",
    "type": "object",
    "required": ["schema", "schema_version", "generated_at", "plan", "approval", "ready_for_generation", "public", "evidence", "validation", "revisions"],
    "properties": {
        "schema": {"const": SCHEMA_ID}, "schema_version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"}, "generated_at": _NUM,
        "generator": _OBJ,
        "plan": _obj(["id", "project_id", "story_id", "format", "target_minutes", "duration_s", "content_hash", "working_title", "title_is_working", "story_nature",
                      "verification", "export_rev"], {
            "id": _STR, "project_id": _STR, "story_id": _STR, "format": {"enum": ["16:9", "9:16"]}, "target_minutes": _NUM, "duration_s": _NUM,
            "content_hash": _STR, "working_title": _STR, "title_is_working": {"const": True}, "story_nature": _STR,
            "verification": {"enum": ["unverified", "verified"]}, "export_rev": _INT, "language": _STR}),
        "approval": _obj(["state"], {"state": {"enum": ["draft", "approved", "changed"]}, "at": _NUM, "note": _STR, "warnings": _STRS, "content_hash": _STR}),
        "ready_for_generation": _obj(["ok", "blockers", "warnings"], {"ok": {"type": "boolean"}, "blockers": _STRS, "warnings": _STRS}),
        "public": _obj(["narrator", "blueprint", "narration", "scenes", "assets", "image_models", "production_notes"], {
            "narrator": _obj(["person", "language", "script", "voice"], {"name": _STR, "person": _STR, "gender": _STR, "language": _STR, "script": _STR, "voice": _STR, "avatar": _OBJ}),
            "blueprint": _obj(["structure", "beats"], {"structure": _STR, "viewer_promise": _STR, "central_question": _STR,
                                                      "beats": {"type": "array", "minItems": 1, "items": _obj(["id", "name", "purpose"], {"id": _STR, "name": _STR, "purpose": _STR, "takeaway": _STR})}}),
            "narration": _obj(["segments"], {"segments": {"type": "array", "minItems": 1, "items": SEGMENT}}),
            "scenes": {"type": "array", "minItems": 1, "items": SCENE},
            "assets": {"type": "array", "items": ASSET},
            "image_models": _obj(["default", "by_type", "providers"], {"default": _STR, "by_type": _OBJ, "providers": _OBJ}),
            "production_notes": _obj(["tts", "images"], {"tts": _OBJ, "images": _OBJ})}),
        "evidence": _obj(["story", "segments", "scenes", "research_gaps", "publishing_checklist"], {
            "story": _obj(["candidate_id", "project_id"], {"candidate_id": _STR, "project_id": _STR, "paragraph_ids": {"type": "array", "items": _INT}, "pages": {"type": "array"},
                                                         "claims": {"type": "array", "items": _OBJ}, "flags": {"type": "array"}, "scores": _OBJ, "figures": {"type": "array", "items": _OBJ}}),
            "segments": _OBJ, "scenes": _OBJ, "assets": _OBJ, "research_gaps": _STRS, "publishing_checklist": {"type": "array", "items": _obj(["item", "done"], {"item": _STR, "done": {"type": "boolean"}})}}),
        "validation": _obj(["narration", "storyboard", "prompts", "public_leak_check", "scores"], {
            "narration": _OBJ, "storyboard": _OBJ, "prompts": _OBJ,
            "public_leak_check": _obj(["ok", "findings"], {"ok": {"type": "boolean"}, "findings": {"type": "array"}}),
            "scores": _obj(["dimensions", "summary", "disclaimer"], {"dimensions": {"type": "array", "minItems": 12, "maxItems": 12, "items": DIMENSION}, "summary": _OBJ, "disclaimer": _STR})}),
        "revisions": _obj(["count", "recent"], {"count": _INT, "recent": {"type": "array", "items": _obj(["ts", "what"], {"ts": _NUM, "what": _STR, "detail": _OBJ})}}),
    },
}
