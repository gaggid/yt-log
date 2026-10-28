"""Phase 2 batch B: continuity registry, scenes aligned to narration, timing, validation.

The scene record saved here is the single authoritative description of a shot. It never contains a provider-specific prompt as
its only form: Qwen and FLUX prompts (batch C) are compiled from it and stored beside it.

Alignment: a scene points at a segment and a run of its sentences. Start and end times are DERIVED from the narration
(sentence length + pauses), never typed in, so editing narration or reordering segments re-times everything consistently.
"""
import re
import uuid

from story import db, llm, settings as settings_mod, storytypes
from . import describe, director, intake, leak, maya, planner, prompts as P, providers, store, styles, svara
from .scene_schemas import ASPECTS, NEEDS_ASSET, RegistryOut, SceneOut, ScenesOut

MIN_SCENE_S, MAX_SCENE_S = 2.0, 20.0
MAX_SAME_TYPE_RUN = 3


# ── helpers ─────────────────────────────────────────────────────────────────

_NUMWORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
             "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
             "eighty": 80, "ninety": 90, "hundred": 100}


def fact_numbers(text: str) -> set[str]:
    """Every number the facts mention, as digits, counting spelled-out numbers ("four sessions" -> 4)."""
    out = {m.strip(",.") for m in re.findall(r"\d[\d,.]*", text)}
    out |= {str(v) for w, v in _NUMWORDS.items() if re.search(rf"\b{w}\b", text.lower())}
    return {x for x in out if x}

def sentence_seconds(seg: dict, wpm: float, real_s: float | None = None) -> list[float]:
    """Seconds per sentence: estimated from the words, or, when the segment has real audio, spread over its measured length in the same proportions."""
    est = [svara.spoken_seconds(x["text"], wpm, x.get("pause_after_s") or 0) for x in seg["sentences"]]
    total = sum(est)
    return [e * real_s / total for e in est] if real_s and total else est


def real_audio(plan_id: str) -> dict[str, float]:
    """Measured audio length per segment (Phase 3 voice), or nothing when no voice has been made."""
    try:
        from story3 import store as media
        return media.audio_seconds(plan_id)
    except Exception:  # noqa: BLE001 - timing must never fail because media is unavailable
        return {}


def _scene_row(r: dict) -> dict:
    r["data"] = db.jload(r["data"], {})
    r["issues"] = db.jload(r["issues"], [])
    r["locked"], r["stale"] = bool(r["locked"]), bool(r["stale"])
    return r


def _beat_visual_brief_text(blueprint: dict | None, beat_id: str) -> str:
    """The visual brief for one beat, formatted as a storyboard instruction block. Empty string when no brief exists."""
    b = next((x for x in ((blueprint or {}).get("beats") or []) if x.get("id") == beat_id), {})
    pv = (b.get("primary_visual") or "").strip()
    unf = [x for x in (b.get("unfilmable") or []) if x]
    vd = (b.get("visual_device") or "").strip()
    if not pv and not unf:
        return ""
    parts = []
    if pv:
        parts.append(f"Show first in this beat: {pv}. Plan at least one scene whose subject IS this — not a character reacting to it.")
    if unf:
        parts.append(f"Concepts that cannot be filmed directly: {'; '.join(unf)}.")
    if vd:
        parts.append(f"Decided visual device: {vd}. Use this device; do not invent another.")
    return "BEAT VISUAL BRIEF:\n" + " ".join(parts) + "\n\n"


def get_scenes(plan_id: str) -> list[dict]:
    store.ensure()
    rows = db.q("SELECT * FROM scenes WHERE plan_id=? ORDER BY seq, id", (plan_id,))
    return [_scene_row(r) for r in rows]


def get_assets(plan_id: str) -> list[dict]:
    store.ensure()
    out = db.q("SELECT * FROM assets WHERE plan_id=? ORDER BY CASE kind WHEN 'style' THEN 0 WHEN 'narrator' THEN 1 ELSE 2 END, rowid", (plan_id,))
    for a in out:
        a["data"] = db.jload(a["data"], {})
        a["locked"] = bool(a["locked"])
    return out


def _asset_lines(assets: list[dict]) -> str:
    return "\n".join(f"- {a['name']} ({a['kind']}): {a['data'].get('description', '')}"
                     + (f" | always: {'; '.join(a['data'].get('fixed', []))}" if a["data"].get("fixed") else "")
                     + (f" | {a['data'].get('fictionalisation', '')}" if a["kind"] == "person" else "") for a in assets)


def _seq(seg: dict, n: int) -> float:
    return seg["seq"] + n / 1000


_NOT_AN_OBJECT = re.compile(r"\b(chart|graph|diagram|infographic|report|document|spreadsheet|statement|filing)\b", re.I)
# Ideas are not things. A figure of speech, a chart feature or a theme has no shape to draw: the image model invents one (a glowing beam, a robot). Props must be
# physical objects that are in the scene, and a crowd is not one person. The registry model says so itself (`literal`); these words catch what it misses, in any
# subject (finance, crime, science, history).
_ABSTRACT_PROP = re.compile(r"\b(idea|concept|theme|metaphor|symbol|pattern|indicator|trend|signal|feeling|emotion|mood|atmosphere|rumou?r|theory|principle|strategy)\b", re.I)
_FIGURATIVE_NOTE = re.compile(r"\b(metaphor\w*|symboli[sz]\w*|represent\w*|visuali[sz]\w*|stands? for|figure of speech|abstract\w*)\b", re.I)
_GROUP_PERSON = re.compile(r"\b(crowd|crowds|mob|public|audience|everyone|everybody|people|group|team|staff|villagers|citizens|protesters|the masses|the world)\b", re.I)


_STOPWORDS = {"that", "this", "with", "from", "have", "their", "there", "which", "about", "into", "over", "under", "while", "where", "when", "scene", "shot", "view", "close",
              "wide", "frame", "light", "dark", "behind", "front", "background", "foreground", "person", "figure", "looking", "standing", "sitting", "holding", "inside", "outside"}


def _content_words(text: str) -> set[str]:
    return {w[:4] for w in re.findall(r"[a-z]{5,}", text.lower()) if w not in _STOPWORDS}          # four-letter stems: trader, trading and trade are the same thing


def not_drawable(kind: str, name: str, appearance: dict, note: str) -> str:
    """Why a registry entry cannot be drawn as one thing, or an empty string when it can."""
    if kind == "prop":
        if _NOT_AN_OBJECT.search(name + " " + appearance.get("type", "")):
            return "a chart, graph or document is built from facts later"
        if _ABSTRACT_PROP.search(name + " " + appearance.get("type", "")):
            return "an idea or pattern has no shape to draw"
        if _SUBSTANCE.search(name.strip().split(" ")[-1] if name.strip() else ""):
            return "a liquid, gas, surface or light has no fixed shape: it belongs to the place or the scene, not to a prop"
        if _FIGURATIVE_NOTE.search(note or ""):
            return "it stands for an idea in the narration rather than being an object in the scene"
    if kind == "place" and _COMPARISON.search(note or ""):
        return "the narration only compares the story to this; it is not somewhere the story's people are"
    if kind == "place" and _NOT_A_PLACE.search(name + " " + appearance.get("type", "")):
        return "a place must be somewhere that physically exists (a room, street, field, building), not a space, grid or concept"
    if kind == "person" and _GROUP_PERSON.search(name):
        return "a group is not one person: name the individual roles instead"
    return ""


_SUBSTANCE = re.compile(r"^(water|waters|sewage|stream|streams|flow|flows|river|rivers|puddles?|smoke|steam|fog|mist|dust|mud|fire|flames?|blood|rain|snow|ice|floor|floors|ground|surface|air|light|shadows?|sky|darkness|waste|filth)$", re.I)
_COMPARISON = re.compile(r"(like an? |as if|as though|\b(analog|simile|compar|resembl|similar to|imagine|picture a|think of))", re.I)
_FX = re.compile(r"\b(pulse|burst|aura|energy|radiat\w*|ripples?|swirl\w*|vortex|beam|shockwave|shock wave)\b", re.I)
_NOT_A_PLACE = re.compile(r"\b(abstract|void|limbo|grid|dimension|realm|virtual|digital|cyber\w*|matrix|infinite|empty space|conceptual|metaphor\w*|mindscape|dreamscape)\b", re.I)
_NOWHERE = re.compile(r"\b(abstract|void|nowhere|limbo|blank|empty space|infinite|undefined|unknown|none|n/a)\b", re.I)


def scene_problems(scenes: list, assets: list[dict]) -> list[str]:
    """Why a designed scene would not be a picture of the story. Works for any subject: a scene must happen somewhere, to someone.
    A scene that is only an idea (a line, a symbol, a floating object in 'abstract space') is sent back to be translated into a moment."""
    people = {a["name"].lower() for a in assets if a["kind"] == "person"}
    places = {a["name"].lower() for a in assets if a["kind"] == "place"}
    if not people and not places:
        return []                                                   # no registry to hold the scene to
    out = []
    for i, sc in enumerate(scenes, 1):
        if sc.visual_type in NEEDS_ASSET:
            continue                                                # built from verified facts later, with a full illustrated fallback
        used = {n.lower() for n in sc.assets}
        where = f"scene {i} ({sc.subject[:50]})"
        if _NOWHERE.search(sc.location or "") or (not (sc.location or "").strip() and not used & places):
            out.append(f"{where}: the location is '{sc.location}'. Every picture happens in a real place of the story's world (use a place from the list).")
        if not (used & people or used & places):
            out.append(f"{where}: it shows neither a person nor a place from the continuity list. Do not draw the idea itself (a line, a shape, a symbol, an object floating "
                       "in space). Translate it: who in the story is living this idea, where, doing what, with what on their face.")
    for i, sc in enumerate(scenes, 1):
        if sc.visual_type not in NEEDS_ASSET and _FX.search(f"{sc.subject} {sc.action}"):
            out.append(f"scene {i} ({sc.subject[:50]}): it draws an effect (a pulse, burst, glow, energy, vortex) instead of something in the world. Show a person reacting, "
                       "an object, or the place, as it would look to someone standing there.")
    out += _monotony(scenes, people, places)
    return out


def _monotony(scenes: list, people: set, places: set) -> list[str]:
    """Scenes in a row that keep the same place or the same lone person. Only asked for when the registry has somewhere else to go."""
    out = []
    for kind, pool, limit, what in (("place", places, 3, "happen in the same place"), ("person", people, 2, "show the same person alone")):
        if len(pool) < 2:
            continue
        run, last = 0, None
        for i, sc in enumerate(scenes, 1):
            used = frozenset(n.lower() for n in sc.assets) & pool
            key = used if kind == "place" or len(used) == 1 else None
            run = run + 1 if key and key == last else (1 if key else 0)
            last = key
            if run == limit + 1:
                alt = sorted(pool - set(key))
                out.append(f"scene {i}: {limit + 1} scenes in a row {what}. Move this one to a different {kind} ({', '.join(alt[:4])}) or add someone else.")
    return out


# ── registry ────────────────────────────────────────────────────────────────

LIKENESS = ("real_person_likeness", "real_person_stylised")           # set by the editor in story3/likeness.py; kept when the characters are created again


async def make_registry(plan_id: str, backend, s: dict | None = None) -> dict:
    s = s or settings_mod.get()
    plan = planner.get_plan(plan_id)
    story = planner._story_for(plan)
    bp = plan["blueprint"] or {}
    user = ("STORY FACTS:\n" + intake.facts_text(story["public"]) + "\n\nVIDEO PLAN: "
            + (bp.get("viewer_promise", "") + " Structure: " + bp.get("structure", "")).strip()
            + "\nNARRATION (the picture list must cover everyone and everything in it):\n" + "\n".join(x["plain"] for x in plan["segments"])[:7000]
            + "\nNarrator: a first-person guide shown as an animated avatar (do not list the narrator as an asset)."
            + f"\nVISUAL STYLE of the whole video (the style asset is set for you; draw characters and places to fit it): {styles.for_plan(plan['settings'])['look']}"
            + ("\nCAST: every person in this video is Indian. Fill the ethnicity slot with Indian (add the region or community only when the story names one) and give "
               "skin, hair and eyes that fit an Indian person; use Indian names and clothes that fit the period and place. Places and objects follow the story's own setting."
               if describe.indian_on(plan["settings"]) else
               "\nCAST: do not default to any one ethnicity. Choose each person's ethnicity, skin, hair, eyes, name and clothes from the story's own country, region, period and community "
               "(use the names and places in the story facts); when the story does not say, pick what is most plausible for that place and time."))
    tries: list[int] = []

    def enough(out: RegistryOut) -> None:
        tries.append(1)
        real = [x for x in out.assets if x.kind in ("person", "place") and x.literal and not not_drawable(x.kind, x.name, x.appearance, x.evidence_note)]
        places, people = [x for x in real if x.kind == "place"], [x for x in real if x.kind == "person"]
        if len(tries) <= 2 and (len(places) < 3 or len(people) < 2):
            raise ValueError(f"The list has {len(places)} real place(s) and {len(people)} person(s) that can be drawn. A place is somewhere that physically exists (never a space, grid or idea). "
                             "Give the story at least 3 different real places it moves through and at least 2 people (the main person and supporting people).")

    res = await llm.JsonCaller(backend, s).call(P.REGISTRY, user, RegistryOut, enough)
    kept = {a["name"].lower(): a for a in get_assets(plan_id) if a["locked"]}
    named = {a["name"].lower(): {k: a["data"][k] for k in ("public_figure", "fictionalisation", "likeness_photos") if k in a["data"]}
             for a in get_assets(plan_id) if a["kind"] == "person" and not a["locked"] and a["data"].get("fictionalisation") in LIKENESS}     # the editor's choices about real people
    with db.tx() as c:
        c.execute("DELETE FROM assets WHERE plan_id=? AND locked=0", (plan_id,))
        for a in res.value.assets:
            if a.name.lower() in kept:
                continue
            if a.kind == "style":
                continue                                            # the style asset is written from the chosen preset below
            if a.kind in ("prop", "person", "place") and (not a.literal or not_drawable(a.kind, a.name, a.appearance, a.evidence_note)):
                continue                                            # charts, ideas and groups are never listed as one drawable thing
            data = a.model_dump()
            data["name"] = a.name = re.sub(r"\s+style$", "", a.name.strip(), flags=re.I) or a.name           # the model sometimes tacks the word "style" onto every name
            ap = describe.clean(data.get("appearance"))
            if ap and a.kind in ("person", "narrator") and describe.indian_on(plan["settings"]):
                ap = describe.indianise(ap)                         # the cast setting is enforced here too, not left to the model's wording
            if ap:                                                  # the description the image model reads is composed from the slots, so no slot is dropped
                data["appearance"] = ap
                data["description"] = describe.describe(a.kind, ap) or data["description"]
                data["fixed"] = describe.fixed_from(a.kind, ap) or data["fixed"]
            if a.kind == "person" and a.name.lower() in named:
                data.update(named[a.name.lower()])
            c.execute("INSERT INTO assets(id,plan_id,kind,name,data,updated_at) VALUES(?,?,?,?,?,?)",
                      ("as-" + uuid.uuid4().hex[:8], plan_id, a.kind, a.name, db.jdump(data), db.now()))
        if not any(a["kind"] == "style" for a in kept.values()):
            c.execute("INSERT INTO assets(id,plan_id,kind,name,data,updated_at) VALUES(?,?,?,?,?,?)",
                      ("as-" + uuid.uuid4().hex[:8], plan_id, "style", "style", db.jdump(styles.style_asset_data(plan["settings"])), db.now()))
        # the narrator avatar is always registered, as a design placeholder (creating the avatar is outside this module)
        if not any(a["kind"] == "narrator" for a in get_assets(plan_id)):
            c.execute("INSERT INTO assets(id,plan_id,kind,name,data,updated_at) VALUES(?,?,?,?,?,?)",
                      ("as-" + uuid.uuid4().hex[:8], plan_id, "narrator", "narrator", db.jdump({
                          "name": "narrator", "kind": "narrator", "description": "", "fixed": [], "flexible": [],
                          "fictionalisation": "fictional", "evidence_note": "avatar to be designed", "status": "to be designed"}), db.now()))
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**planner.get_plan(plan_id)["settings"], "registry_direction": styles.DIRECTION, "registry_style": styles.style_id(plan["settings"])}), db.now(), plan_id))
    store.log(plan_id, "registry", {"assets": len(get_assets(plan_id))})
    return planner.get_plan(plan_id)


def apply_cast(plan_id: str) -> int:
    """Write the Indian cast into the character list: ethnicity, and colouring that cannot go with it, replaced in the slots; description and fixed details are
    composed again. Unlocked and locked people alike (the owner chose it for every plan). Returns how many people changed."""
    n = 0
    for a in get_assets(plan_id):
        ap = a["data"].get("appearance")
        if a["kind"] not in ("person", "narrator") or not ap:
            continue
        new = describe.indianise(ap)
        if new == describe.clean(ap):
            continue
        data = {**a["data"], "appearance": new, "description": describe.describe(a["kind"], new) or a["data"].get("description", "")}
        data["fixed"] = describe.fixed_from(a["kind"], new) or data.get("fixed", [])
        db.ex("UPDATE assets SET data=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(data), db.now(), a["id"]))
        n += 1
    store.log(plan_id, "cast_indian", {"changed": n})
    return n


# ── scene construction ──────────────────────────────────────────────────────

def repair_coverage(ranges: list[list[int]], n: int) -> list[list[int]]:
    """Make scene sentence ranges cover 1..n exactly once, in order. Gaps extend the previous scene, overlaps are trimmed."""
    rs = sorted((r[:2] if len(r) >= 2 else [r[0], r[0]] for r in ranges if r), key=lambda r: (r[0], r[1]))
    out, nxt = [], 1
    for a, b in rs:
        a, b = max(a, nxt), min(b, n)
        if b < a:
            continue
        if a > nxt and out:
            out[-1][1] = a - 1                                       # a gap: the previous scene holds until this one starts
        elif a > nxt:
            a = nxt
        out.append([a, b])
        nxt = b + 1
    if not out:
        return [[1, n]]
    out[-1][1] = n
    return out


def follow_shots(scenes: list, shots: list[dict], force: bool = False) -> list[str]:
    """Tie each scene to a director's shot (by its own "shot" number, else by position) and report scenes whose camera differs from the shot. With
    `force` the shot's size, angle and move are written into the scene, so the plan always reaches the picture prompt and the video."""
    off = []
    if not shots:
        return off
    for k, sc in enumerate(scenes):
        n = sc.shot if 1 <= sc.shot <= len(shots) else min(len(shots), int(k * len(shots) / len(scenes)) + 1)
        sh = shots[n - 1]
        sc.shot = n
        if director._size(sc.composition.distance) != sh["size"] or director._angle(sc.composition.camera_angle) != sh["angle"]:
            off.append(f"scene {k + 1} follows shot {n} ({sh['size']}, {sh['angle']}) but its camera is {sc.composition.distance or 'unset'}, {sc.composition.camera_angle or 'unset'}")
        if force:
            sc.composition.distance, sc.composition.camera_angle = sh["size"], sh["angle"]
            sc.motion_intent = "static hold" if sh["move"] == "hold" else f"slow {sh['move']}"
    return off


def _compose_intent(d: dict) -> str:
    place = ", ".join(x for x in (d["setting"]["location"], d["setting"]["period"]) if x)
    comp = d["composition"]
    cam = ", ".join(x for x in (comp.get("camera_angle"), comp.get("distance")) if x)
    parts = [f"{d['subject']} {d['action']}".strip(), place, f"camera: {cam}" if cam else "", d["lighting"], d["style"]]
    return ". ".join(x for x in parts if x).strip()


def build_scene(sc: SceneOut, assets: list[dict], plan: dict, evidence_ids: list[int]) -> tuple[dict, list[str]]:
    by_name = {a["name"].lower(): a["id"] for a in assets}
    ids, unknown = [], []
    for n in sc.assets:
        (ids if n.lower() in by_name else unknown).append(by_name.get(n.lower(), n))
    w, h = ASPECTS.get(plan["format"], ASPECTS["16:9"])
    d = {
        "narrative": {"purpose": sc.purpose, "new_information": sc.new_information, "takeaway": sc.takeaway,
                      "emotional_effect": sc.emotional_effect},
        "voice_tag": sc.voice_tag,
        "visual_type": sc.visual_type, "subject": sc.subject, "action": sc.action,
        "setting": {"location": sc.location, "period": sc.period, "props": sc.props},
        "composition": sc.composition.model_dump(), "lighting": sc.lighting, "palette": sc.palette, "atmosphere": sc.atmosphere,
        "style": sc.style, "layers": {"foreground": sc.foreground, "middle": sc.middle, "background": sc.background},
        "motion_intent": sc.motion_intent, "direction": {"shot": sc.shot, "move": director._move(sc.motion_intent)}, "text_on_screen": [t.model_dump() for t in sc.text_on_screen],
        "facts": {"fixed": sc.fixed_by_facts, "creative": sc.creative_choices},
        "evidence_ids": evidence_ids, "continuity": {"assets": ids, "unknown": unknown},
        "output": {"aspect_ratio": plan["format"], "width": w, "height": h},
        "exclusions": sc.exclusions, "prompts": {}, "adapters": {},
        "translation": {"idea": sc.idea, "moment": sc.translation},
    }
    needs = sc.visual_type in NEEDS_ASSET
    d["feasibility"] = {
        "level": "needs_asset" if needs else "ok",
        "needs_asset": (sc.needs_asset or "verified content for this visual, built from the story's own facts") if needs else "",
        "fallback": (sc.fallback or "show the setting around it with no readable data") if needs else sc.fallback,
        "notes": "an image model must not draw this content; build it deterministically from verified facts" if needs else ""}
    d["generation_intent"] = _compose_intent(d)
    return d, unknown


def apply_voice_tags(seg_id: str) -> None:
    """Copy each scene's suggested voice tag onto the narration sentences it covers. The tag is what Maya is told; nothing else about the wording changes."""
    row = db.one("SELECT sentences FROM segments WHERE id=?", (seg_id,))
    if not row:
        return
    sents = db.jload(row["sentences"], [])
    for r in db.q("SELECT s_from, s_to, data FROM scenes WHERE segment_id=?", (seg_id,)):
        tag = db.jload(r["data"], {}).get("voice_tag") or ""
        for i in range(r["s_from"], min(r["s_to"], len(sents)) + 1):
            sents[i - 1]["tag"] = tag
    db.ex("UPDATE segments SET sentences=? WHERE id=?", (db.jdump(sents), seg_id))


def _insert_scene(c, plan_id: str, seg: dict, n: int, rng: list[int], data: dict) -> str:
    sid = "sc-" + uuid.uuid4().hex[:8]
    c.execute("INSERT INTO scenes(id,plan_id,seq,segment_id,s_from,s_to,data,updated_at) VALUES(?,?,?,?,?,?,?,?)",
              (sid, plan_id, _seq(seg, n), seg["id"], rng[0], rng[1], db.jdump(data), db.now()))
    return sid


def _prev_summary(scenes: list[dict]) -> str:
    if not scenes:
        return "none yet: this is the first scene of the video."
    return "\n".join(f"- {s['data']['visual_type']}, {s['data']['composition'].get('distance', '')} {s['data']['composition'].get('camera_angle', '')}: "
                     f"{s['data']['subject']}" for s in scenes[-3:])


async def make_storyboard(plan_id: str, backend, s: dict | None = None, segment_ids: list[str] | None = None,
                          progress=None, replace_approved: bool = False) -> dict:
    """Scenes for each narration segment. A segment holding a locked or approved scene is left untouched, unless `replace_approved` (a new
    visual direction): then only locked scenes are kept."""
    s = s or settings_mod.get()
    plan = planner.get_plan(plan_id)
    if not plan["segments"]:
        raise planner.PlanError("write the narration first")
    if not get_assets(plan_id):
        await make_registry(plan_id, backend, s)
    if not director.current(plan):
        plan = await director.make(plan_id, backend, s)                     # the whole film is planned as shots before any scene is drawn
    ordered_segs = sorted(plan["segments"], key=lambda x: x["seq"])
    story = planner._story_for(plan)
    facts = intake.facts_text(story["public"])
    ev = story["evidence"]["paragraph_ids"]
    wpm = plan["settings"].get("wpm", planner.WPM)
    real = real_audio(plan_id)
    caller = llm.JsonCaller(backend, s)
    todo = [x for x in plan["segments"] if not segment_ids or x["id"] in segment_ids]
    protected = {sc["segment_id"] for sc in get_scenes(plan_id) if sc["locked"] or (sc["status"] == "approved" and not replace_approved)}
    look = styles.for_plan(plan["settings"])
    done = 0
    for seg in todo:
        done += 1
        if progress:
            progress(done - 1, len(todo), f"segment {done} of {len(todo)}")
        if seg["id"] in protected:
            continue
        assets = get_assets(plan_id)
        secs = sentence_seconds(seg, wpm, real.get(seg["id"]))
        n = len(secs)
        lines = "\n".join(f"{i}. ({secs[i - 1]:.1f}s) {x['text']}" for i, x in enumerate(seg["sentences"], 1))
        prior = [x for x in get_scenes(plan_id) if x["seq"] < seg["seq"]]
        idx = next(i for i, x in enumerate(ordered_segs, 1) if x["id"] == seg["id"])
        shots = director.shots_for(plan, idx)
        nxt = ordered_segs[idx]["sentences"][0]["text"][:160] if idx < len(ordered_segs) and ordered_segs[idx]["sentences"] else "the video ends."
        beat_brief = _beat_visual_brief_text(plan["blueprint"], seg["beat"])
        user = (f"STORY FACTS:\n{facts}\n\nVISUAL STYLE (every scene is drawn in it): {look['short']}. {look['look']}\n\n"
                f"CONTINUITY ASSETS (use these names in \"assets\"):\n{_asset_lines(assets)}\n\n"
                f"STORY MAP (>> is this segment):\n{director.story_map(plan, idx)}\n\n"
                f"DIRECTOR'S SHOT LIST for this segment (follow it):\n{director.shot_list(plan, idx)}\n\n"
                f"WHAT COMES NEXT: {nxt}\n\n"
                f"PREVIOUS SCENES (do not repeat their composition):\n{_prev_summary(prior)}\n\n"
                + beat_brief
                + f"THIS SEGMENT (beat {seg['beat']}), {n} sentence(s), {sum(secs):.1f} s:\n{lines}\n\n"
                "Design the scenes for this segment now.")

        def fix(out: ScenesOut, n=n, shots=shots) -> None:
            rngs = repair_coverage([sc.sentences for sc in out.scenes], n)
            if len(rngs) != len(out.scenes):                         # ranges collapsed: keep scenes in order, re-split
                out.scenes = out.scenes[:len(rngs)]
            for sc, r in zip(out.scenes, rngs):
                sc.sentences = r
            tries.append(1)
            last = len(tries) > 2 or caller.last_attempt                 # sent back with the reasons, then on the last attempt accepted and left to the checks
            off = follow_shots(out.scenes, shots, force=last)
            bad = [] if last else scene_problems(out.scenes, assets)
            if not last and (bad or off):
                raise ValueError("These scenes are not right yet:\n- " + "\n- ".join(bad + off))

        tries: list[int] = []
        for again in range(3):                                       # a long segment can come back as broken JSON three times running: ask again before giving up
            tries.clear()
            try:
                res = await caller.call(P.SCENES + storytypes.scenes_note(storytypes.of_plan(plan)), user, ScenesOut, fix)
                break
            except llm.ValidationFailed:
                if again == 2:
                    raise
        with db.tx() as c:
            c.execute("DELETE FROM scenes WHERE segment_id=? AND locked=0" + ("" if replace_approved else " AND status!='approved'"), (seg["id"],))
            for k, sc in enumerate(res.value.scenes):
                data, _ = build_scene(sc, assets, plan, ev)
                _insert_scene(c, plan_id, seg, k, sc.sentences, data)
        apply_voice_tags(seg["id"])
        retime(plan_id)
    if progress:
        progress(len(todo), len(todo), "done")
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?",
          (db.jdump({**planner.get_plan(plan_id)["settings"], "storyboard_direction": styles.DIRECTION, "storyboard_style": look["id"]}), db.now(), plan_id))
    store.log(plan_id, "storyboard", {"segments": len(todo), "style": look["id"]})
    return planner.get_plan(plan_id)


async def regenerate_scene(scene_id: str, backend, s: dict | None = None, note: str = "") -> dict:
    """Redo one scene over the same sentences. Nothing else is touched. `note` tells the model what to change."""
    s = s or settings_mod.get()
    row = db.one("SELECT * FROM scenes WHERE id=?", (scene_id,))
    if not row:
        raise planner.PlanError("scene not found")
    sc0 = _scene_row(row)
    if sc0["locked"]:
        raise planner.PlanError("this scene is locked; unlock it first")
    plan = planner.get_plan(sc0["plan_id"])
    seg = next(x for x in plan["segments"] if x["id"] == sc0["segment_id"])
    story = planner._story_for(plan)
    secs = sentence_seconds(seg, plan["settings"].get("wpm", planner.WPM), real_audio(plan["id"]).get(seg["id"]))
    a, b = sc0["s_from"], sc0["s_to"]
    lines = "\n".join(f"{i}. ({secs[i - 1]:.1f}s) {seg['sentences'][i - 1]['text']}" for i in range(a, b + 1))
    assets = get_assets(plan["id"])
    prev = [x for x in get_scenes(plan["id"]) if x["seq"] < sc0["seq"]]
    user = (f"STORY FACTS:\n{intake.facts_text(story['public'])}\n\nVISUAL STYLE (every scene is drawn in it): {styles.for_plan(plan['settings'])['look']}\n\n"
            f"CONTINUITY ASSETS:\n{_asset_lines(assets)}\n\n"
            f"PREVIOUS SCENES (do not repeat their composition):\n{_prev_summary(prev)}\n\n"
            f"Design exactly ONE scene for sentences {a} to {b} of this segment (use \"sentences\": [{a}, {b}]):\n{lines}\n"
            + (f"\nEditor's request: {note}\n" if note else "") + f"\nThe scene being replaced: {sc0['data']['subject']} / {sc0['data']['action']}")

    tries: list[int] = []

    def one(out: ScenesOut) -> None:
        out.scenes = out.scenes[:1]
        out.scenes[0].sentences = [a, b]
        tries.append(1)
        if len(tries) <= 2 and (bad := scene_problems(out.scenes, assets)):
            raise ValueError("This scene is not a picture of the story:\n- " + "\n- ".join(bad))

    res = await llm.JsonCaller(backend, s).call(P.SCENES + storytypes.scenes_note(storytypes.of_plan(plan)), user, ScenesOut, one)
    data, _ = build_scene(res.value.scenes[0], assets, plan, story["evidence"]["paragraph_ids"])
    db.ex("UPDATE scenes SET data=?, rev=rev+1, stale=0, status='draft', issues='[]', updated_at=? WHERE id=?",
          (db.jdump(data), db.now(), scene_id))
    apply_voice_tags(seg["id"])
    store.log(plan["id"], "scene_regenerated", {"id": scene_id, "note": note})
    return get_scene(scene_id)


def scrub_numbers(scene_id: str, numbers: list[str]) -> None:
    """Remove words that must not be there (a number not in the story's facts, a phrase copied from the source) from a scene's own wording."""
    nums = [n for n in numbers if n]
    sc = get_scene(scene_id)

    def clean(x):
        if isinstance(x, str):
            for n in nums:
                x = re.sub(r"(?<![0-9A-Za-z])" + re.escape(n) + r"(?![0-9A-Za-z])", "", x, flags=re.I)
            return re.sub(r"\s{2,}", " ", x).strip(" ,;")
        if isinstance(x, list):
            return [clean(v) for v in x]
        if isinstance(x, dict):
            return {k: clean(v) if k not in ("prompts", "previews", "adapters") else v for k, v in x.items()}
        return x
    db.ex("UPDATE scenes SET data=?, rev=rev+1, status='draft', issues='[]', updated_at=? WHERE id=?", (db.jdump(clean(sc["data"])), db.now(), scene_id))


def get_scene(scene_id: str) -> dict:
    r = db.one("SELECT * FROM scenes WHERE id=?", (scene_id,))
    if not r:
        raise planner.PlanError("scene not found")
    return _scene_row(r)


# ── timing and alignment ────────────────────────────────────────────────────

def retime(plan_id: str) -> float:
    """Derive every scene's start, end and duration from the current narration. Returns total seconds."""
    plan = planner.get_plan(plan_id)
    wpm = plan["settings"].get("wpm", planner.WPM)
    real = real_audio(plan_id)
    by_seg: dict[str, list[dict]] = {}
    for sc in get_scenes(plan_id):
        by_seg.setdefault(sc["segment_id"], []).append(sc)
    t = 0.0
    with db.tx() as c:
        for seg in plan["segments"]:
            sd = sentence_seconds(seg, wpm, real.get(seg["id"]))
            for sc in sorted(by_seg.get(seg["id"], []), key=lambda x: x["s_from"]):
                a, b = max(1, sc["s_from"]), min(len(sd), sc["s_to"])
                st = t + sum(sd[:a - 1])
                en = t + sum(sd[:b]) if b >= a else st
                c.execute("UPDATE scenes SET start_s=?, end_s=?, duration_s=? WHERE id=?",
                          (round(st, 2), round(en, 2), round(en - st, 2), sc["id"]))
            t += sum(sd)
    return round(t, 2)


def on_segment_changed(seg_id: str, old_n: int, new_n: int) -> None:
    """Narration of a segment changed. Keep its scenes, spread them over the new sentences, and mark them for a quick look."""
    scenes = sorted([x for x in get_scenes_for_segment(seg_id)], key=lambda x: x["s_from"])
    if not scenes:
        return
    if new_n != old_n:
        k = len(scenes)
        old = [max(1, x["s_to"] - x["s_from"] + 1) for x in scenes]
        total = sum(old)
        if new_n >= k:
            counts = [max(1, round(o * new_n / total)) for o in old]
            while sum(counts) > new_n:
                counts[counts.index(max(counts))] -= 1
            while sum(counts) < new_n:
                counts[counts.index(min(counts))] += 1
        else:
            counts = [1] * new_n + [0] * (k - new_n)
        pos = 1
        with db.tx() as c:
            for sc, cnt in zip(scenes, counts):
                if cnt:
                    c.execute("UPDATE scenes SET s_from=?, s_to=? WHERE id=?", (pos, pos + cnt - 1, sc["id"]))
                    pos += cnt
                else:
                    c.execute("UPDATE scenes SET s_from=0, s_to=-1 WHERE id=?", (sc["id"],))     # no narration left for it
    db.ex("UPDATE scenes SET stale=1, updated_at=? WHERE segment_id=? AND locked=0", (db.now(), seg_id))


def get_scenes_for_segment(seg_id: str) -> list[dict]:
    return [_scene_row(r) for r in db.q("SELECT * FROM scenes WHERE segment_id=? ORDER BY s_from", (seg_id,))]


def after_narration(plan_id: str) -> None:
    """Narration segments were replaced. Scenes of vanished segments go, unless locked or approved (then they show as orphaned)."""
    ids = {s["id"] for s in planner.list_segments(plan_id)}
    for sc in get_scenes(plan_id):
        if sc["segment_id"] not in ids and not (sc["locked"] or sc["status"] == "approved"):
            db.ex("DELETE FROM scenes WHERE id=?", (sc["id"],))
    retime(plan_id)


def move_segment(seg_id: str, direction: int) -> dict:
    """Reorder narration (and with it its scenes) by swapping with the neighbour; all timing is re-derived."""
    seg = db.one("SELECT plan_id FROM segments WHERE id=?", (seg_id,))
    if not seg:
        raise planner.PlanError("segment not found")
    segs = planner.list_segments(seg["plan_id"])
    i = next(k for k, x in enumerate(segs) if x["id"] == seg_id)
    j = i + (1 if direction > 0 else -1)
    if not 0 <= j < len(segs):
        raise planner.PlanError("already at the " + ("end" if direction > 0 else "start"))
    a, b = segs[i], segs[j]
    with db.tx() as c:
        for x, new in ((a, b["seq"]), (b, a["seq"])):
            c.execute("UPDATE segments SET seq=?, rev=rev+1 WHERE id=?", (new, x["id"]))
            for sc in get_scenes_for_segment(x["id"]):
                c.execute("UPDATE scenes SET seq=? WHERE id=?", (new + (sc["seq"] - x["seq"]), sc["id"]))
    retime(seg["plan_id"])
    store.log(seg["plan_id"], "segment_moved", {"id": seg_id, "direction": direction})
    return planner.get_plan(seg["plan_id"])


# ── editing ─────────────────────────────────────────────────────────────────

def _deep_set(d: dict, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def edit_scene(scene_id: str, patch: dict) -> dict:
    """patch keys: dotted paths into the scene record (e.g. "composition.distance", "subject"), plus status, locked."""
    sc = get_scene(scene_id)
    if sc["locked"] and patch.keys() - {"locked", "model", "voice_tag"}:
        raise planner.PlanError("this scene is locked; unlock it first")
    data, sets, args = sc["data"], [], []
    protected = {"prompts", "adapters", "previews", "output", "evidence_ids", "continuity"}
    for k, v in patch.items():
        if k == "status":
            if v not in ("draft", "edited", "approved", "rejected"):
                raise planner.PlanError("status must be draft, edited, approved or rejected")
            sets.append("status=?")
            args.append(v)
            if v == "approved":
                sets.append("stale=0")
        elif k == "locked":
            sets.append("locked=?")
            args.append(1 if v else 0)
        elif k == "model":
            if v and v not in providers.PROVIDERS:
                raise planner.PlanError(f"unknown image model '{v}' (use one of: {', '.join(providers.PROVIDERS)})")
            data["model"] = v or ""
        elif k == "voice_tag":
            data["voice_tag"] = maya.norm_tag(v)
        elif k.split(".")[0] in protected:
            raise planner.PlanError(f"{k} is managed by the planner and cannot be edited here")
        else:
            _deep_set(data, k, v)
    if set(patch) <= {"model", "voice_tag"}:
        sets += ["data=?"]                                          # the image model and the voice tag are production settings, not an edit of the scene
        args.append(db.jdump(data))
    elif set(patch) - {"status", "locked"}:
        data["generation_intent"] = _compose_intent(data)
        if data["visual_type"] in NEEDS_ASSET:
            data["feasibility"]["level"] = "needs_asset"
        sets += ["data=?", "stale=0"]
        args.append(db.jdump(data))
        if "status" not in patch:
            sets.append("status='edited'")
    db.ex(f"UPDATE scenes SET {', '.join(sets)}, rev=rev+1, issues='[]', updated_at=? WHERE id=?", [*args, db.now(), scene_id])
    if "voice_tag" in patch:
        apply_voice_tags(sc["segment_id"])
    store.log(sc["plan_id"], "scene", {"id": scene_id, "fields": list(patch)})
    return get_scene(scene_id)


_DISTANCES = ("wide", "medium", "close-up", "medium close-up", "extreme close-up")
_ANGLES = ("eye-level", "low", "high", "over-the-shoulder", "side")


def _set_camera(sc: dict, prev: tuple, nxt: tuple | None) -> None:
    """Give a scene a camera distance and angle that match neither neighbour; the framing text is left as the model wrote it."""
    for dist in _DISTANCES:
        for ang in _ANGLES:
            if (dist, ang) != prev and (dist, ang) != nxt and dist != prev[0]:
                comp = {**sc["data"]["composition"], "distance": dist, "camera_angle": ang}
                db.ex("UPDATE scenes SET data=?, rev=rev+1, stale=0, status='draft', updated_at=? WHERE id=?",
                      (db.jdump({**sc["data"], "composition": comp}), db.now(), sc["id"]))
                return


async def fix_repeats(plan_id: str, backend, s: dict | None = None, progress=None) -> int:
    """Redraw, one by one and in order, every unlocked scene that repeats the previous scene's camera distance and angle."""
    cam = lambda sc: (sc["data"]["composition"].get("distance", "").strip().lower(), sc["data"]["composition"].get("camera_angle", "").strip().lower())  # noqa: E731
    first = [sc for sc in sorted(get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"]))]
    todo = [cur["id"] for prev, cur in zip(first, first[1:]) if cam(prev) == cam(cur) and all(cam(prev)) and not cur["locked"]]
    done = fixed = 0
    for sid in todo:
        ordered = sorted(get_scenes(plan_id), key=lambda x: x["start_s"])
        i = next(k for k, x in enumerate(ordered) if x["id"] == sid)
        if progress:
            progress(done, len(todo), f"scene {done + 1} of {len(todo)}")
        done += 1
        if i == 0 or cam(ordered[i - 1]) != cam(ordered[i]):
            continue                                              # an earlier redraw already fixed this one
        nxt = f" and from the next scene ({'/'.join(cam(ordered[i + 1]))})" if i + 1 < len(ordered) else ""
        note = (f"Keep the same story beat and subject idea, but change the camera. The previous scene used distance "
                f"'{cam(ordered[i - 1])[0]}' and angle '{cam(ordered[i - 1])[1]}'; use a clearly different distance AND a different angle{nxt}.")
        await regenerate_scene(sid, backend, s, note)
        fixed += 1
        ordered = sorted(get_scenes(plan_id), key=lambda x: x["start_s"])
        if cam(ordered[i - 1]) == cam(ordered[i]):                # the model kept the camera: change it directly so the run never stalls on one scene
            _set_camera(ordered[i], cam(ordered[i - 1]), cam(ordered[i + 1]) if i + 1 < len(ordered) else None)
    swept = _sweep_repeats(plan_id)                               # a redraw can leave a new repeat with the next scene: settle every one that is left, so pressing the button once is enough
    retime(plan_id)
    if progress:
        progress(len(todo), len(todo), "done")
    store.log(plan_id, "fix_repeats", {"redrawn": fixed, "camera_changed": swept})
    return fixed + swept


def _sweep_repeats(plan_id: str) -> int:
    """Change the camera of every unlocked scene that still has the camera of the scene before it. Needs no model, goes in order, looks at both neighbours, so it ends."""
    cam = lambda sc: (sc["data"]["composition"].get("distance", "").strip().lower(), sc["data"]["composition"].get("camera_angle", "").strip().lower())  # noqa: E731
    n = 0
    for _ in range(3):
        ordered = sorted(get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"]))
        changed = False
        for i in range(1, len(ordered)):
            if cam(ordered[i]) == cam(ordered[i - 1]) and all(cam(ordered[i])) and not ordered[i]["locked"]:
                _set_camera(ordered[i], cam(ordered[i - 1]), cam(ordered[i + 1]) if i + 1 < len(ordered) else None)
                ordered = sorted(get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"]))
                n += 1
                changed = True
        if not changed:
            break
    return n


# ── validation ──────────────────────────────────────────────────────────────

def validate_storyboard(plan_id: str) -> dict:
    plan = planner.get_plan(plan_id)
    story = planner._story_for(plan)
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    facts = intake.facts_text(story["public"]).lower()
    known_numbers = fact_numbers(facts)
    scenes = get_scenes(plan_id)
    seg_ids = {s["id"] for s in plan["segments"]}
    issues: list[dict] = []

    def add(sc, kind, text, level="error"):
        issues.append({"where": sc["id"] if sc else "plan", "kind": kind, "text": text, "level": level})

    cov: dict[str, list[int]] = {s["id"]: [0] * len(s["sentences"]) for s in plan["segments"]}
    for sc in scenes:
        d = sc["data"]
        n = d["narrative"]
        if sc["segment_id"] not in seg_ids:
            add(sc, "orphan", "its narration segment no longer exists")
            continue
        if sc["s_to"] < sc["s_from"] or sc["s_from"] < 1:
            add(sc, "no_narration", "no narration is left for this scene; remove or regenerate it")
        else:
            for i in range(sc["s_from"], min(sc["s_to"], len(cov[sc["segment_id"]])) + 1):
                cov[sc["segment_id"]][i - 1] += 1
        if not n["purpose"].strip():
            add(sc, "purpose", "no narrative purpose")
        if not n["new_information"].strip():
            add(sc, "new_information", "does not say what is new for the viewer compared with the previous picture", "warn")
        if sc["stale"]:
            add(sc, "stale", "the narration changed; check this scene still fits", "warn")
        if not (MIN_SCENE_S <= sc["duration_s"] <= MAX_SCENE_S) and sc["s_to"] >= sc["s_from"]:
            add(sc, "duration", f"lasts {sc['duration_s']:.1f}s (expected {MIN_SCENE_S:g} to {MAX_SCENE_S:g}s)", "warn")
        if d["continuity"]["unknown"]:
            add(sc, "assets", "uses assets that are not in the registry: " + ", ".join(d["continuity"]["unknown"]), "warn")
        for t in d["text_on_screen"]:
            if len(t["text"].split()) > 8:
                add(sc, "text", "on-screen text is longer than 8 words")
            for num in re.findall(r"\d[\d,.]*", t["text"]):
                if num.strip(",.") and num.strip(",.") not in known_numbers and num.strip(",.") not in facts:
                    add(sc, "text", f"on-screen number {num} is not in the story's facts")
        if d["visual_type"] in NEEDS_ASSET and not d["feasibility"]["needs_asset"]:
            add(sc, "feasibility", "needs a verified asset but none is described")
        text = " . ".join([d["subject"], d["action"], d["generation_intent"], *[t["text"] for t in d["text_on_screen"]],
                           d["narrative"]["purpose"], d["narrative"]["takeaway"]])
        for f in leak.check(text, prof, scene=True):
            add(sc, "source_leak", f"{f.kind}: {f.text}")
    for seg in plan["segments"]:
        c = cov[seg["id"]]
        if any(scn["segment_id"] == seg["id"] for scn in scenes):
            gaps = [i + 1 for i, v in enumerate(c) if v == 0]
            dup = [i + 1 for i, v in enumerate(c) if v > 1]
            if gaps:
                issues.append({"where": seg["id"], "kind": "coverage", "text": f"sentences {gaps} have no scene", "level": "error"})
            if dup:
                issues.append({"where": seg["id"], "kind": "coverage", "text": f"sentences {dup} are in more than one scene", "level": "error"})
        else:
            issues.append({"where": seg["id"], "kind": "coverage", "text": "no scenes yet for this narration", "level": "warn"})
    # timing: scene time must equal narration time
    wpm, real = plan["settings"].get("wpm", planner.WPM), real_audio(plan_id)
    total = sum(sum(sentence_seconds(s, wpm, real.get(s["id"]))) for s in plan["segments"])           # the basis retime() uses, so the two cannot drift apart by rounding
    scene_total = sum(sc["duration_s"] for sc in scenes if sc["segment_id"] in seg_ids)
    if scenes and abs(total - scene_total) > 0.5 and not any(i["kind"] == "coverage" for i in issues):
        issues.append({"where": "plan", "kind": "timing", "text": f"scenes add up to {scene_total:.1f}s but narration is {total:.1f}s", "level": "error"})
    # variety
    ordered = sorted([sc for sc in scenes if sc["segment_id"] in seg_ids], key=lambda x: (x["start_s"], x["seq"]))
    for prev, cur in zip(ordered, ordered[1:]):
        a, b = prev["data"], cur["data"]
        cam = lambda d: (d["composition"].get("distance", "").strip().lower(), d["composition"].get("camera_angle", "").strip().lower())  # noqa: E731
        if cam(a) == cam(b) and cam(a)[0] and cam(a)[1]:
            add(cur, "repeat", "same camera distance and angle as the previous scene: change one of them", "warn")
    run = 1
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if prev["data"]["visual_type"] == cur["data"]["visual_type"] else 1
        if run == MAX_SAME_TYPE_RUN + 1:
            add(cur, "variety", f"more than {MAX_SAME_TYPE_RUN} scenes in a row of type {cur['data']['visual_type']}", "warn")
    world = _content_words(intake.facts_text(story["public"]) + " " + " ".join(f"{x['name']} {x['data'].get('description', '')} {x['data'].get('period', '')}" for x in get_assets(plan_id) if x["kind"] != "style"))
    for sc in ordered:
        d = sc["data"]
        mine = _content_words(" ".join([d.get("subject", ""), d.get("action", ""), str((d.get("setting") or {}).get("location", "")), " ".join(map(str, (d.get("setting") or {}).get("props", [])))]))
        if len(mine) >= 4 and not (mine & world):
            add(sc, "unrelated", "nothing in this scene appears in the story's facts or among its characters, places and objects: check that it belongs to this story", "warn")
    need = [sc for sc in ordered if sc["data"]["feasibility"]["level"] == "needs_asset"]
    rights = [f for f in story["evidence"]["figures"] if f.get("rights_flag")]
    if need and rights:
        issues.append({"where": "plan", "kind": "figures", "text": f"{len(need)} scene(s) need a chart or document; the source's own figures carry a rights notice and are not reusable: rebuild from facts", "level": "warn"})
    report = {"ok": not any(i["level"] == "error" for i in issues), "issues": issues, "scenes": len(scenes),
              "scene_seconds": round(scene_total, 1), "narration_seconds": round(total, 1),
              "types": {t: sum(1 for sc in ordered if sc["data"]["visual_type"] == t) for t in sorted({sc["data"]["visual_type"] for sc in ordered})}}
    by_scene: dict[str, list] = {}
    for i in issues:
        by_scene.setdefault(i["where"], []).append(i)
    for sc in scenes:
        db.ex("UPDATE scenes SET issues=? WHERE id=?", (db.jdump(by_scene.get(sc["id"], [])), sc["id"]))
    db.ex("UPDATE plans SET validation=?, updated_at=? WHERE id=?",
          (db.jdump({**(plan["validation"] or {}), "storyboard": report}), db.now(), plan_id))
    return report
