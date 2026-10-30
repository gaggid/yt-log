"""The cast of a short: characters (and one place) chosen from the Character Studio library. A short with a cast draws its start pictures by image edit from the characters' canon pictures
(and the place's), so the same faces come back in every shot, instead of describing a person again in every prompt. At most two people and a place per shot (the gateway takes three reference
pictures per edit). See docs/PLAN_characters.md section 6."""
from characters import render, requests as CR, store as cstore, studio_edit
from story3 import store as media

MAX_PEOPLE = 2


def entries(short: dict) -> list[dict]:
    return [e for e in (short["settings"].get("cast") or []) if e.get("character_id")]


def members(short: dict) -> list[dict]:
    """Each cast member with its library character, the picture it wears (a look, else the canon body), the canon pictures and a name. Raises nothing: a missing character is reported by `problems`."""
    out = []
    for e in entries(short):
        try:
            c = cstore.get(e["character_id"])
        except cstore.CharError:
            out.append({"entry": e, "char": None})
            continue
        canon = cstore.canon_items(c)
        look = studio_edit.look_item(c, e.get("look_id", "")) if e.get("look_id") else None
        out.append({"entry": e, "char": c, "canon": canon, "wear": look or canon.get("body"), "look_name": next((x["name"] for x in c["looks"] if x["id"] == e.get("look_id")), "")})
    return out


def place(short: dict) -> dict | None:
    pid = short["settings"].get("place_id") or ""
    if not pid:
        return None
    try:
        c = cstore.get(pid)
    except cstore.CharError:
        return {"char": None, "item": None}
    return {"char": c, "item": cstore.canon_items(c).get("place")}


def problems(short: dict) -> list[str]:
    out = []
    ms = members(short)
    if len(ms) > MAX_PEOPLE:
        out.append(f"at most {MAX_PEOPLE} characters in a short (an edit takes three pictures: two people and the place)")
    for m in ms:
        if not m["char"]:
            out.append("a character of the cast is no longer in the library")
        elif "portrait" not in m["canon"] or not m["wear"]:
            out.append(f"approve a portrait and a full-body picture of {m['char']['name']} in the Characters studio first")
    pl = place(short)
    if pl and (not pl["char"] or not pl["item"]):
        out.append("the place of the short has no approved picture in the Characters studio")
    return out


def block(short: dict) -> str:
    """The cast as text for the planner: name, the written description, and the look worn."""
    lines = []
    for m in members(short):
        if not m["char"]:
            continue
        c = m["char"]
        look = next((x for x in c["looks"] if x["id"] == m["entry"].get("look_id")), None)
        wears = f" Wears: {look['recipe'].get('value')}." if look and look["recipe"].get("value") else (f" Wears the look '{look['name']}'." if look else "")
        lines.append(f"{c['name']}: {CR.identity_text(c).rstrip('.')}.{wears}" + (f" Mood: {c['personality']}." if c.get("personality") else ""))
    return "\n".join(lines)


def names(short: dict) -> dict[str, str]:
    """{lower-case name: character id}"""
    return {m["char"]["name"].strip().lower(): m["char"]["id"] for m in members(short) if m["char"]}


def place_text(short: dict) -> str:
    pl = place(short)
    return CR.identity_text(pl["char"]).rstrip(".") + "." if pl and pl["char"] else ""


def look_text(short: dict) -> str:
    ms = [m for m in members(short) if m["char"]]
    return render.look(ms[0]["char"]["render"]) if ms else ""


def refs_for(short: dict, shot: dict) -> dict | None:
    """The reference pictures for the start picture of a shot, in the order the prompt names them: the people in the shot (their look or canon body; a lone person also gets the face portrait first),
    then the place. None when the shot has no cast member (it is drawn from text). A cast member with only a portrait approved still gets references — portrait used as the sole identity anchor."""
    ids = shot.get("cast") or []
    ms = [m for m in members(short) if m["char"] and m["char"]["id"] in ids][:MAX_PEOPLE]
    if not ms or any("portrait" not in m["canon"] for m in ms):
        return None
    pics, who = [], []
    if len(ms) == 1:
        pics.append(ms[0]["canon"]["portrait"])
        who.append((ms[0]["char"]["name"], "face"))
    for m in ms:
        if m["wear"]:
            pics.append(m["wear"])
            who.append((m["char"]["name"], "whole body" + (f", look {m['look_name']}" if m["look_name"] else "")))
    pl = place(short)
    use_place = bool(pl and pl["item"] and not shot.get("setting"))
    if use_place and len(pics) < 3:
        pics.append(pl["item"])
    elif use_place:
        pics = pics[:2] + [pl["item"]]
        who = who[:2]
    return {"pics": pics, "who": who, "place": use_place and pics[-1] is pl["item"], "versions": {m["char"]["id"]: m["char"]["version"] for m in ms}, "chars": ms,
            "paths": [media.path_of(p) for p in pics], "ids": [p["id"] for p in pics]}
