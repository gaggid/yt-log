"""The video's YouTube thumbnail: one movie-poster style picture with a short curiosity question on it, drawn by Qwen Image 2.1. A model writes the question (and what
the picture shows) from the story plan; the picture is drawn with the words in quotes, which Qwen draws best; a vision check reads the words back and the best attempt is
approved. The poster look follows the plan's visual style, so the thumbnail and the video belong together."""
import asyncio
from pathlib import Path
import base64
import re
import time
from typing import Annotated

import httpx
from PIL import Image
from pydantic import BaseModel, BeforeValidator, ConfigDict, field_validator

from story import db, llm, settings as settings_mod
from story.schemas import Str
from story2 import imgprompts, intake, leak, planner, prompts as P, providers, storyboard, store as plan_store

from . import refscore, scenes, store
from .voice import MediaError

KIND = "thumbnail"
KEY = "thumbnail"
MAX_WORDS = 8
OUT_SIZE = (1280, 720)

def _words(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().strip("\"'")


class Option(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: Annotated[str, BeforeValidator(_words)]
    image: Str = ""                           # what the poster shows: who or what, where, what the face or the object says
    why: Str = ""

    @field_validator("text")
    @classmethod
    def _ok(cls, v):
        if not v or len(v.split()) > MAX_WORDS or len(v.split()) < 2:
            raise ValueError(f"the words on the thumbnail must be 2 to {MAX_WORDS} words")
        if not imgprompts.latin_only(v):
            raise ValueError("the words on the thumbnail must use English letters only")
        return v


class ThumbOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    options: list[Option]

    @field_validator("options")
    @classmethod
    def _n(cls, v):
        if not v:
            raise ValueError("no thumbnail options")
        return v


def _hero(plan_id: str) -> tuple[dict | None, dict | None]:
    """The person and the place that appear in the most scenes: the face and the setting of the poster."""
    use: dict[str, int] = {}
    for sc in storyboard.get_scenes(plan_id):
        for a in sc["data"].get("continuity", {}).get("assets", []):
            use[a] = use.get(a, 0) + 1
    assets = sorted(storyboard.get_assets(plan_id), key=lambda a: -use.get(a["id"], 0))
    return next((a for a in assets if a["kind"] == "person"), None), next((a for a in assets if a["kind"] == "place"), None)


def hero_line(person: dict | None) -> str:
    """Who the face is: gender, age and the look the registry gave this person ("a 62-year-old man (lean, grey stubble)"). An unspecified "South Asian adult" had produced two
    women's faces for a film about one man."""
    if not person:
        return "one South Asian adult"
    ap = person["data"].get("appearance") or {}
    gender = str(ap.get("gender") or "").strip().lower()
    age = re.search(r"\d+", str(ap.get("age") or ""))
    who = f"a {age.group(0)}-year-old {gender or 'person'}" if age else f"a {gender or 'person'}"
    look = "; ".join(str(ap.get(k)).strip() for k in ("build", "face", "hair") if str(ap.get(k) or "").strip())
    return who + (f" ({look})" if look else "")


def read_back_ok(wanted: str, read: str) -> bool:
    """The picture shows the wanted words and nothing else readable: a few stray letters are tolerated, a garbled map label or a second line of words is not."""
    w, r = refscore._norm(wanted), refscore._norm(read)
    return bool(w) and w in r and len(r.replace(w, "", 1)) <= 3


BY_CODE_TAIL = (" Keep the lower third of the frame calm and dark with no detail, so a headline can be placed there. There is no text, no letter, no number, no logo and no watermark "
                "anywhere in the picture.")


def indian_money(text: str) -> str:
    """Rupee amounts in Indian style for a headline: 64 crore as ₹64 crore, 5 lakh as ₹5 lakh (words, not millions)."""
    return re.sub(r"(?<![\w₹])(\d[\d,.]*)\s*(crore|lakh)\b", lambda m: f"₹{m.group(1)} {m.group(2)}", text, flags=re.I)


def headline_font(text: str, size: int):
    """A heavy face for the headline: Nirmala UI Bold when the text has Devanagari, else a heavy Latin sans."""
    from PIL import ImageFont
    names = ["C:/Windows/Fonts/NirmalaB.ttf"] if re.search(r"[ऀ-ॿ]", text) else ["C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
    for n in names:
        if Path(n).is_file():
            return ImageFont.truetype(n, size)
    return ImageFont.load_default()


def compose_headline(path: Path, text: str) -> list[str]:
    """Write the headline on the picture, in code, in the lower third: big capitals, a thick dark stroke and a shadow, white with the last word in yellow. Nothing a model draws can be
    garbled, and a Hindi or Hinglish headline is possible. Returns the lines written."""
    from PIL import ImageDraw
    text = indian_money(" ".join(text.split()))
    im = Image.open(path).convert("RGB")
    w, h = im.size
    d = ImageDraw.Draw(im)
    words = text.upper().split() if not re.search(r"[ऀ-ॿ]", text) else text.split()
    box_w, box_h = int(w * 0.92), int(h * 0.30)
    lines, size, f = [], int(h * 0.20), None
    while size >= 28:
        f = headline_font(text, size)
        lines, cur = [], ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if d.textbbox((0, 0), trial, font=f)[2] <= box_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        lines.append(cur)
        if len(lines) <= 2 and len(lines) * size * 1.08 <= box_h:
            break
        size -= 4
    y = h - int(h * 0.04) - int(len(lines) * size * 1.08)
    for k, ln in enumerate(lines):
        tw = d.textbbox((0, 0), ln, font=f)[2]
        x = (w - tw) / 2
        stroke = max(4, size // 9)
        d.text((x + stroke, y + stroke), ln, font=f, fill=(150, 20, 20), stroke_width=stroke, stroke_fill=(150, 20, 20))                      # red drop shadow
        head, _, last = ln.rpartition(" ")
        if k == len(lines) - 1 and head:
            d.text((x, y), head + " ", font=f, fill=(255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0))
            hw = d.textbbox((0, 0), head + " ", font=f)[2]
            d.text((x + hw, y), last, font=f, fill=(255, 224, 40), stroke_width=stroke, stroke_fill=(0, 0, 0))
        else:
            d.text((x, y), ln, font=f, fill=(255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += int(size * 1.08)
    im.save(path, optimize=True)
    return lines


def small_legible(path: Path, text: str) -> bool:
    """The thumbnail at the size of a suggested-video tile (170 by 95): is the headline still there? Checked by contrast in the lower third: bright pixels and dark pixels both present."""
    im = Image.open(path).convert("L").resize((170, 95), Image.LANCZOS)
    band = list(im.crop((0, 62, 170, 95)).getdata())
    bright = sum(1 for v in band if v > 225)
    dark = sum(1 for v in band if v < 40)
    return bright >= len(band) * 0.04 and dark >= len(band) * 0.10


def _fallback_prompt(opt: Option, person: dict | None, by_code: bool = False) -> str:
    """Baseline prompt used when the LLM enhancement step fails or is skipped."""
    who = imgprompts._s(opt.image) or "the story's main character in dramatic close-up"
    if person and person["data"].get("fictionalisation") == "real_person_no_likeness":
        who += "; shown only as a silhouette, from behind or in shadow, no recognisable face"
    return (f"Photorealistic YouTube thumbnail, wide 16:9 frame. Composite image: "
            f"left third shows a dramatic emotional close-up of {hero_line(person)} (shock or fear, eyes wide, face fills the area); this is the only face in the image; "
            f"right two-thirds shows two stacked panels with key story scenes without faces, maps or written words: {who}. "
            f"High contrast, vivid colours, dark panel backgrounds, bright warm light on the face. "
            + (BY_CODE_TAIL.strip() if by_code else
               f'Exact text: the words "{opt.text}" in very large bold all-capital letters, white with thick black stroke and red drop shadow, '
               f"across the bottom of the image. Written once, spelled exactly as quoted. No other text, logo or watermark."))


async def _enhance_prompt(opt: Option, blueprint: dict, be, s: dict, person: dict | None = None) -> str:
    """Call the text LLM to expand the composite concept into a detailed Qwen image prompt.
    Falls back to the template prompt if the LLM call fails."""
    user = (f"CONCEPT:\n{opt.image}\n\n"
            f"WORDS ON THUMBNAIL: \"{opt.text}\"\n\n"
            f"THE FACE: {hero_line(person)}. Exactly one face in the whole image; the panels show hands, objects or places, never a second face, a map or written words.\n\n"
            f"BLUEPRINT:\nPromise: {blueprint.get('viewer_promise', '')}\n"
            f"Cold open: {blueprint.get('cold_open', '')}\nAt stake: {blueprint.get('stakes', '')}\n\n"
            f"Write the image generation prompt now.")
    try:
        result = await be.complete([{"role": "system", "content": P.THUMBNAIL_PROMPT_BOOST},
                                    {"role": "user", "content": user}], max_tokens=600)
        enhanced = result.content.strip()
        return enhanced if len(enhanced.split()) > 20 else ""
    except Exception:  # noqa: BLE001 - template is the safe fallback
        return ""


async def make(plan_id: str, be, s: dict | None = None, key: str = "", progress=None, candidates: int = 3) -> dict:
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    plan = planner.get_plan(plan_id)
    bp = plan["blueprint"] or {}
    if not bp:
        raise MediaError("plan the story first")
    story = planner._story_for(plan)
    person, place = _hero(plan_id)
    facts = intake.facts_text(story["public"])
    user = (f"STORY FACTS:\n{facts}\n\nVIDEO PLAN:\nPromise: {bp.get('viewer_promise', '')}\nCentral question: {bp.get('central_question', '')}\nCold open: {bp.get('cold_open', '')}\n"
            f"At stake: {bp.get('stakes', '')}\nThe wrong answer first: {bp.get('false_answer', '')}\nPayoff: {bp.get('payoff', '')}\n\n"
            f"MAIN PERSON: {person['name'] if person else 'none'} ({hero_line(person)}): the face on the thumbnail is this person. MAIN PLACE: {place['name'] if place else 'none'}.\nWrite the thumbnail options now.")
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    known = storyboard.fact_numbers(facts.lower())

    def check(out: ThumbOut) -> None:
        bad = [o.text for o in out.options if re.search(r"\d", o.text) and not all(n.strip(",.") in known for n in re.findall(r"\d[\d,.]*", o.text))]
        bad += [o.text for o in out.options if leak.check(o.text, prof, scene=True)]
        if bad:
            raise ValueError("these words are not allowed on the thumbnail (a number that is not in the story's facts, or wording from the source): " + " | ".join(bad[:3]))

    res = await llm.JsonCaller(be, s).call(P.THUMBNAIL, user, ThumbOut, check)
    opt = res.value.options[0]
    cfg = providers.get("qwen-image-2.1")
    w, h, _ = providers.snap(1344, 768, cfg)
    out_dir = store.media_dir(plan_id, "thumbnail")
    base = s["base_url"].rstrip("/")
    if progress:
        progress(0, candidates, "writing the thumbnail prompt")
    enhanced = await _enhance_prompt(opt, bp, be, s, person)
    by_code = bool((plan["settings"].get("thumbnail") or {}).get("text_by_code", True))                   # the headline is written in code after the picture is drawn (task 6.2)
    prompt = enhanced or _fallback_prompt(opt, person, by_code)
    if by_code and enhanced:
        prompt += BY_CODE_TAIL
    if leak.check_many([(KEY, prompt)], prof):
        raise MediaError("the thumbnail prompt would carry source wording")
    made = []
    async with httpx.AsyncClient(timeout=700) as client:
        for n in range(candidates):
            if progress:
                progress(n, candidates, f"drawing the thumbnail ({n + 1} of {candidates})")
            it = store.add(plan_id, KIND, KEY, 0, "running", {"model": "qwen-image-2.1", "text": opt.text, "prompt": prompt, "image_idea": opt.image})
            seed = scenes.seed_for(KEY, it["attempt"])
            t0 = time.time()
            try:
                img = await scenes._post(client, base + "/images/generations", key, json={"model": "qwen-image-2.1", "prompt": prompt, "size": f"{w}x{h}", "n": 1, "seed": seed, "response_format": "b64_json"})
            except asyncio.CancelledError:
                store.update(it["id"], status="failed", meta={"error": "stopped before it finished"})
                raise
            except MediaError as e:
                store.update(it["id"], status="failed", meta={"error": str(e)[:300]})
                continue
            raw = out_dir / f"thumbnail-a{it['attempt']}.png"
            raw.write_bytes(base64.b64decode(img["b64_json"]))
            Image.open(raw).convert("RGB").resize(OUT_SIZE, Image.LANCZOS).save(raw, optimize=True)         # the size YouTube asks for
            read, note = "", ""
            if by_code:
                lines = compose_headline(raw, opt.text)
                ok = small_legible(raw, opt.text)
                made.append(store.update(it["id"], status="done", file=f"thumbnail/{raw.name}", meta={"seed": seed, "seconds_taken": round(time.time() - t0, 1), "text_read": " ".join(lines), "text_ok": ok,
                                                                                                        "note": "" if ok else "the headline is hard to read at the size of a suggested video", "headline_by_code": True}))
                if ok:
                    break
                continue
            try:
                seen = await refscore.look(raw, {"kind": "scene", "name": "", "brief": f'A movie-poster thumbnail. It should show the words "{opt.text}" once, spelled exactly. {opt.image}'}, "", s, key)
                read = seen.get("text_read", "")
            except Exception as e:  # noqa: BLE001 - the picture is kept; the reading is only a check
                note = f"vision check unavailable: {str(e)[:100]}"
            ok = read_back_ok(opt.text, read)                                                              # the words and nothing else readable (no garbled map labels)
            made.append(store.update(it["id"], status="done", file=f"thumbnail/{raw.name}", meta={"seed": seed, "seconds_taken": round(time.time() - t0, 1), "text_read": read, "text_ok": ok, "note": note}))
            if ok:
                break                                                                                      # words drawn exactly as asked: no need for another try
    if not made:
        raise MediaError("the thumbnail could not be drawn")
    best = next((m for m in made if m["meta"].get("text_ok")), made[0])
    store.approve(best["id"])
    plan_store.log(plan_id, "thumbnail", {"text": opt.text, "attempts": len(made), "text_ok": bool(best["meta"].get("text_ok"))})
    if progress:
        progress(candidates, candidates, "done")
    return {"item": store.get(best["id"]), "options": [o.model_dump() for o in res.value.options]}


def state(plan_id: str) -> dict:
    items = [i for i in store.items(plan_id, KIND, KEY) if i["status"] == "done"]
    ap = next((i for i in items if i["approved"]), None)
    pick = ap or (items[-1] if items else None)
    return {"done": bool(ap), "item": pick and {"id": pick["id"], "url": f"/api/media/file/{plan_id}/{pick['file']}", "text": pick["meta"].get("text", ""), "text_ok": pick["meta"].get("text_ok"),
                                                  "approved": pick["approved"], "attempt": pick["attempt"], "note": pick["meta"].get("note", "")}, "attempts": len(items)}
