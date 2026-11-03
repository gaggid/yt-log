"""Auto-generate wardrobe items for a character.

LLM plans garments based on city weather, season and fashion taste.
Image model draws each as a flat-lay product shot.
Results saved to the shared wardrobe with basis='invented'.
"""
from story import llm as llm_mod, settings as settings_mod
from story2.schemas import M
from story.schemas import Str

from . import profile as profile_mod, studio, wardrobe, world as world_mod


class _GarmentSpec(M):
    name:        Str       = ""
    description: Str       = ""   # detailed visual for flat-lay prompt
    tags:        list[str] = []
    occasion:    Str       = ""   # casual / work / going-out / exercise / festive / home


class _WardrobePlan(M):
    garments: list[_GarmentSpec] = []


_FLATLAY = ("Flat lay photograph. Clean light background. Top-down product shot. "
            "Natural soft diffused light. Professional fashion photography. "
            "No people, no mannequin, no body parts, no accessories other than the garment.")


async def _plan(char: dict, weather: str, season: str, n: int, backend) -> list[dict]:
    prof     = profile_mod.get(char)
    declared = char.get("declared") or {}
    name     = char.get("name") or "her"
    age      = declared.get("age") or "25"
    gender   = declared.get("gender") or "female"
    city     = prof.get("city") or "India"
    fashion  = prof.get("fashion_taste") or "Indian casual and ethnic wear"
    context  = weather or season or "mild weather"

    system = (f"You are a personal stylist planning a wardrobe for {name}, "
              f"a {age}-year-old {gender} living in {city}, India. "
              f"Fashion sense: {fashion}. Current conditions: {context}. "
              "Generate garments that are realistic, culturally grounded and weather-appropriate. "
              "Mix Indian ethnic (kurtas, co-ords, salwar, dupattas) with casual western. "
              "No duplicates. Cover home, work, casual outings, exercise and festive.")
    user = (f"Return exactly {n} garments as JSON: "
            '{"garments": [{"name": "short name 3-5 words", '
            '"description": "precise flat-lay visual: exact colour, fabric, cut, print or embroidery details — 20-30 words", '
            '"tags": ["occasion"], "occasion": "casual|work|going-out|exercise|festive|home"}]}')

    s      = settings_mod.get()
    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True
    result = await caller.call(system, user, _WardrobePlan)
    return [g.model_dump() for g in (result.value.garments or [])[:n]]


async def generate(char_id: str, n: int, s: dict, key: str) -> list[dict]:
    """Generate n garment flat-lays and save them to the wardrobe. Fire-and-forget safe."""
    from . import store
    char = store.get(char_id)

    # world context for weather / season
    weather = season = ""
    try:
        world  = await world_mod.brief(char)
        weather = world.get("weather", "")
        season  = world.get("season", "")
    except Exception:
        pass

    backend  = llm_mod.ChatBackend(s, key)
    garments = await _plan(char, weather, season, n, backend)

    from . import render as render_mod

    render     = char.get("render", {})
    model      = render.get("model", "")
    base_loras = [{"name": x["name"], "strength": x["strength"]}
                  for x in render.get("loras", []) if x.get("name")]
    existing   = {x["name"] for x in base_loras}
    loras      = base_loras + ([{"name": render_mod.RAW_LORA, "strength": 0.7}] if render_mod.RAW_LORA not in existing else [])
    triggers   = render_mod.trigger_words(render)

    base_url, api_key = studio._ctx(s, key)
    saved = []
    for g in garments:
        prompt   = f"{triggers + ' ' if triggers else ''}{g['description']} {_FLATLAY}"
        body_req = {"model": model, "size": "1024x1024", "n": 1,
                    "response_format": "b64_json", "prompt": prompt[:3900]}
        if loras:
            body_req["lora"] = loras
        try:
            raw  = await studio._post_image("draw", body_req, [], base_url, api_key)
            item = wardrobe.add(raw, g["name"], "invented", g.get("tags") or [], worn=False)
            saved.append(item)
            print(f"[wardrobe-gen] saved: {g['name']}", flush=True)
        except Exception as e:
            print(f"[wardrobe-gen] failed {g['name']}: {e}", flush=True)

    print(f"[wardrobe-gen] done — {len(saved)}/{len(garments)} saved", flush=True)
    return saved
