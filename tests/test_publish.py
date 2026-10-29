"""Tasks 6.1, 6.3, 6.4, 6.5, 6.2 (headline in code) and 6.7: titles, the claim check, the publish pack, subtitles and the thumbnail headline."""
import asyncio

import pytest
from PIL import Image

from story import db
from story2 import claimcheck, planner, titles
from story3 import publish, thumbnail, video
from test_phase3i import ready, make_voice  # noqa: F401
from test_narration_v2 import ready as nready


def narrated(env):
    pid, be = nready(env)
    asyncio.run(planner.make_narration(pid, be))
    return pid, be


def test_the_claim_check_fails_a_number_a_name_or_a_community_the_film_does_not_support(env):
    pid, be = narrated(env)
    p = planner.get_plan(pid)
    assert claimcheck.check("Aakhir kya hua us raat?", p) == []
    assert any("2007" in i for i in claimcheck.check("The 2007 heist", p))
    assert any("Zorblax" in i for i in claimcheck.check("Why did Zorblax run?", p))
    assert any("community" in i for i in claimcheck.check("The hindu lane", p))


def test_titles_are_checked_ranked_and_the_best_is_stored(env):
    pid, be = narrated(env)
    out = asyncio.run(titles.make(pid, be))
    assert out["chosen"] and all(len(o["title"]) <= titles.MAX_LEN for o in out["options"])
    assert {o["register"] for o in out["options"]} == {"hinglish", "hindi", "english"}
    st = planner.get_plan(pid)["settings"]
    assert st["video_title"] == out["chosen"] and st["titles"]["options"]
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**st, "video_title": "My own title", "video_title_auto": False}), pid))
    asyncio.run(titles.make(pid, be))
    assert planner.get_plan(pid)["settings"]["video_title"] == "My own title"                              # an editor's title is never replaced


def test_titles_use_indian_money_style_and_respect_the_audience_order():
    assert titles.indian_style("He lost 64 crore and 5 lakh") == "He lost ₹64 crore and ₹5 lakh"
    assert titles.register_of("आखिर क्या हुआ") == "hindi" and titles.register_of("Aakhir kya hua") == "hinglish" and titles.register_of("What happened") == "english"
    o = titles.PROFILE_ORDER
    assert titles.score("आखिर उस रात क्या हुआ?", {}, o["hindi_first"]) > titles.score("What happened that night?", {}, o["hindi_first"])


def test_srt_times_follow_the_speed():
    s = publish.srt([(0.0, 2.5, "एक"), (2.5, 5.0, "दो")], 1.25)
    assert "00:00:00,000 --> 00:00:02,000" in s and "00:00:02,000 --> 00:00:04,000" in s and s.startswith("1\n")


def test_the_pack_has_every_file_and_the_credit_line_only_in_the_description(env):
    pid, be = narrated(env)
    asyncio.run(titles.make(pid, be))
    plan = planner.get_plan(pid)
    bp = plan["blueprint"]
    for i, b in enumerate(bp["beats"], 1):
        b["chapter_title"] = ["The cold lane", "A phone rings", "Night train", "The last door", "Home again"][i - 1 if i <= 5 else 4]
    db.ex("UPDATE plans SET blueprint=? WHERE id=?", (db.jdump(bp), pid))
    out = asyncio.run(publish.build(pid, be))
    d = publish.publish_dir(pid)
    for f in ("title.txt", "description.txt", "tags.txt", "pinned.txt", "captions-hi.srt", "captions-en.srt", "pack.json"):
        assert (d / f).is_file(), f
    desc = (d / "description.txt").read_text(encoding="utf-8")
    assert out["chapters"][0][0] == "0:00" and "Chapters:" in desc and "AI-generated" in desc
    others = " ".join((d / f).read_text(encoding="utf-8") for f in ("title.txt", "tags.txt", "pinned.txt", "captions-hi.srt"))
    cl = publish.credit_line(planner.get_plan(pid))
    assert cl and cl in desc and cl not in others
    assert publish.state(pid)["title"] == out["title"]


def test_a_title_the_film_does_not_support_stops_the_pack(env):
    pid, be = narrated(env)
    p = planner.get_plan(pid)
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "video_title": "The 2007 Zorblax heist"}), pid))
    with pytest.raises(Exception, match="not in the film"):
        asyncio.run(publish.build(pid, be))


def test_the_headline_is_written_in_code_inside_the_frame_and_is_legible_small(tmp_path):
    img = tmp_path / "t.png"
    Image.new("RGB", (1280, 720), (40, 60, 90)).save(img)
    lines = thumbnail.compose_headline(img, "1 Click 64 crore Gone?")
    assert 1 <= len(lines) <= 2 and Image.open(img).size == (1280, 720)
    assert thumbnail.small_legible(img, "x")
    flat = tmp_path / "f.png"
    Image.new("RGB", (1280, 720), (40, 60, 90)).save(flat)
    assert not thumbnail.small_legible(flat, "x")                                                          # no headline: nothing bright and dark in the lower third
    hi = tmp_path / "h.png"
    Image.new("RGB", (1280, 720), (40, 60, 90)).save(hi)
    assert thumbnail.compose_headline(hi, "आखिर उस रात क्या हुआ")
    assert thumbnail.indian_money("lost 64 crore") == "lost ₹64 crore"
