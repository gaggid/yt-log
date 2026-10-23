"""Batch C: model-aware prompt compilers, provider capabilities, prompt validation, comparison and the explicit preview action."""
import asyncio
import base64

import pytest

from story2 import imgplan, imgprompts, planner, providers, storyboard
from test_phase2a import approved_story, written_plan
from test_phase2b import P2BFake, boarded, scene_json

FACTS_CHART = {"visual_type": "data_chart", "text_on_screen": [{"text": "seventeen percent drop", "placement": "top"}]}


def compiled(env, **kw):
    pid, cid, be, p = boarded(env, **kw)
    rep = imgplan.compile_plan(p["id"])
    return p["id"], storyboard.get_scenes(p["id"]), rep


def test_every_scene_gets_both_prompts_with_the_required_parts(env):
    pid, scenes, rep = compiled(env)
    assert scenes and rep["compiled"] == len(scenes)
    q, f = scenes[0]["data"]["prompts"]["qwen"], scenes[0]["data"]["prompts"]["flux"]
    for label in ("Image objective", "Main subject", "Action and moment", "Environment", "Composition", "Lighting", "Visual treatment",
                  "Colour and mood", "Continuity", "Aspect ratio and framing", "Constraints"):
        assert label + ":" in q["prompt"] or label.split(" and ")[0] + ":" in q["prompt"], label
    assert "Left of frame" in q["prompt"] and "Centre of frame" in q["prompt"] and "Right of frame" in q["prompt"]
    assert "Image objective" not in f["prompt"] and "Constraints:" not in f["prompt"]            # FLUX is prose, not a labelled brief
    assert q["adapter_version"] and f["adapter_version"] and q["model"] == "qwen-image-2.1" and f["model"] == "flux2-klein-9b"
    assert scenes[0]["data"]["adapters"]["qwen"]["version"] == q["adapter_version"]


def test_providers_differ_in_capabilities_and_are_not_interchangeable(env):
    pid, scenes, _ = compiled(env)
    q, f = scenes[0]["data"]["prompts"]["qwen"], scenes[0]["data"]["prompts"]["flux"]
    assert q["negative_prompt"] == "" and f["negative_prompt"] and "logos" in f["negative_prompt"]       # only the base model honours one
    assert (q["params"]["steps"], q["params"]["cfg"]) != (f["params"]["steps"], f["params"]["cfg"])
    assert "must not appear" in q["prompt"].lower() and "logos" in q["prompt"]                        # Qwen: exclusion stated in the prompt
    assert providers.PROVIDERS["qwen-image-2.1"]["negative_prompt"] is False and providers.PROVIDERS["flux2-klein-9b"]["negative_prompt"]
    assert providers.get("flux2-klein-9b")["licence"]["status"] == "restricted" and providers.get("qwen-image-2.1")["licence"]["status"] == "unverified"
    with pytest.raises(providers.ProviderError):
        providers.get("some-future-model")


def test_both_prompts_keep_the_same_canonical_intent_and_validate_clean(env):
    pid, scenes, rep = compiled(env)
    assert not [i for i in rep["issues"] if i["level"] == "error"], rep["issues"]
    sc = scenes[0]
    cmp = imgprompts.comparison(sc, storyboard.get_assets(pid), sc["data"]["prompts"])
    core = {r["element"]: r for r in cmp["coverage"]}
    for el in ("subject", "action", "location", "camera distance", "camera angle", "lighting"):
        assert core[el]["qwen"] and core[el]["flux"], el
    assert cmp["settings"]["qwen"]["negative_prompt"] is False and cmp["settings"]["flux"]["negative_prompt"] is True
    assert cmp["licence"]["flux"]["status"] == "restricted" and "composition adherence" in cmp["evaluate_after_preview"]


def test_continuity_attributes_reach_both_prompts(env):
    pid, scenes, _ = compiled(env)
    for a in ("qwen", "flux"):
        assert "dark jacket" in scenes[0]["data"]["prompts"][a]["prompt"]                            # the registry's fixed attribute
        assert "documentary" in scenes[0]["data"]["prompts"][a]["prompt"].lower()                  # the plan's style asset applies everywhere


def test_charts_and_documents_become_plates_and_text_is_not_drawn(env):
    pid, scenes, rep = compiled(env, scene_over=FACTS_CHART)
    for a in ("qwen", "flux"):
        c = scenes[0]["data"]["prompts"][a]
        assert c["mode"] == "overlay_plate" and "plate" in c["prompt"].lower()
        assert '"seventeen percent drop"' not in c["prompt"] and any("overlay" in n for n in c["notes"])
    assert not any(i["kind"] == "text" and i["level"] == "error" for i in rep["issues"])


def test_short_exact_text_is_quoted_in_both_prompts(env):
    over = {"visual_type": "text_led", "text_on_screen": [{"text": "Day one", "placement": "centre"}]}
    pid, scenes, rep = compiled(env, scene_over=over)
    for a in ("qwen", "flux"):
        assert '"Day one"' in scenes[0]["data"]["prompts"][a]["prompt"]
    assert not any(i["kind"] == "text" for i in rep["issues"])


def test_missing_canonical_details_and_invented_numbers_are_caught(env):
    pid, scenes, _ = compiled(env)
    sc = scenes[0]
    bad = dict(sc["data"]["prompts"]["qwen"])
    bad["prompt"] = "A calm landscape with 4321 birds."
    issues = imgprompts.validate_prompt(bad, sc, storyboard.get_assets(pid), "", None)
    kinds = {i["kind"] for i in issues}
    assert {"missing", "number", "continuity", "exclusion"} <= kinds
    wrong = dict(sc["data"]["prompts"]["qwen"], negative_prompt="blurry")
    assert any(i["kind"] == "negative" for i in imgprompts.validate_prompt(wrong, sc, storyboard.get_assets(pid), "", None))


def test_vague_wording_is_flagged(env):
    pid, scenes, rep = compiled(env, scene_over={"atmosphere": "dramatic and intense"})
    assert any(i["kind"] == "vague" for i in rep["issues"])


def test_source_leak_in_a_prompt_is_an_error(env):
    pid, scenes, rep = compiled(env, scene_over={"action": "holds up the book by the author to the camera"})
    assert any(i["kind"] == "source_leak" and i["level"] == "error" for i in rep["issues"]) and not rep["ok"]


def test_reference_images_are_capped_at_three_and_switch_to_edit_mode(env):
    pid, scenes, _ = compiled(env)
    assets = storyboard.get_assets(pid)
    for a in assets:
        a["data"]["reference_images"] = [{"id": f"img-{a['name']}", "file": "x.png", "approved": True}]
    extra = [{**assets[1], "id": f"extra{i}", "name": f"extra{i}", "kind": "prop", "data": dict(assets[1]["data"])} for i in range(4)]
    sc = scenes[0]
    sc["data"]["continuity"]["assets"] = [a["id"] for a in assets[1:]] + [e["id"] for e in extra]
    plan = planner.get_plan(pid)
    out = imgprompts.compile_scene(sc, assets + extra, plan, imgprompts.first_appearances(scenes))
    for a in ("qwen", "flux"):
        assert len(out[a]["references"]) <= 3 and out[a]["mode"] == "edit" and out[a]["params"]["cfg"] in (2.5, 5.0)
    assert any("only three reference images" in n for n in out["qwen"]["notes"])
    ins = imgprompts.edit_instruction("make the sky stormy", ["the building", "camera angle"], out["qwen"]["references"])
    assert ins.startswith("Change only this: make the sky stormy.") and "Keep unchanged: the building; camera angle." in ins


def test_assets_without_reference_images_are_listed_and_first_appearance_creates_them(env):
    pid, scenes, _ = compiled(env)
    c = scenes[0]["data"]["prompts"]["qwen"]
    assert c["mode"] == "generate" and c["references"] == []
    miss = {m["name"]: m["action"] for m in c["missing_references"]}
    assert miss.get("the trader") == "create_reference"                                               # first scene that uses the person creates the reference


def test_prompts_go_stale_when_the_scene_changes_but_not_when_only_the_model_is_chosen(env):
    pid, scenes, _ = compiled(env)
    sid = scenes[0]["id"]
    storyboard.edit_scene(sid, {"model": "flux2-klein-9b"})
    assert not any(i["kind"] == "stale" for i in imgplan.validate_prompts(pid)["issues"])
    storyboard.edit_scene(sid, {"locked": True})
    storyboard.edit_scene(sid, {"model": "qwen-image-2.1"})                                           # production setting: allowed on a locked scene
    with pytest.raises(planner.PlanError):
        storyboard.edit_scene(sid, {"subject": "someone else"})
    storyboard.edit_scene(sid, {"locked": False})
    storyboard.edit_scene(sid, {"subject": "a different anonymous figure at a desk"})
    assert any(i["kind"] == "stale" and i["where"] == sid for i in imgplan.validate_prompts(pid)["issues"])
    imgplan.compile_plan(pid)
    assert not any(i["kind"] == "stale" for i in imgplan.validate_prompts(pid)["issues"])
    with pytest.raises(planner.PlanError):
        storyboard.edit_scene(sid, {"model": "no-such-model"})
    with pytest.raises(planner.PlanError):
        storyboard.edit_scene(sid, {"prompts": {}})                                                   # derived data cannot be hand-edited


def test_model_choice_by_scene_type_and_licence_is_not_a_blocker_by_default(env):
    pid, scenes, _ = compiled(env)
    plan = imgplan.set_image_models(pid, {"default": "qwen-image-2.1", "by_type": {"character": "flux2-klein-9b"}})
    types = {sc["data"]["visual_type"] for sc in scenes}
    for sc in scenes:
        want = "flux2-klein-9b" if sc["data"]["visual_type"] == "character" else "qwen-image-2.1"
        assert providers.model_for(sc["data"], plan["settings"]) == want
    assert providers.settings_for(plan["settings"])["licence_checks"] == {"qwen-image-2.1": True, "flux2-klein-9b": True}      # owner decision: not a blocker
    assert not any(i["kind"].startswith("licence") for i in imgplan.validate_prompts(pid)["issues"])
    if "character" in types:                                                                                   # a person can still bring the reminder back
        imgplan.set_image_models(pid, {"licence_checks": {"flux2-klein-9b": False}})
        assert any(i["kind"] == "licence_checklist" and i["adapter"] == "flux" for i in imgplan.validate_prompts(pid)["issues"])
    with pytest.raises(providers.ProviderError):
        imgplan.set_image_models(pid, {"default": "nope"})


def test_vertical_plans_are_composed_for_vertical(env):
    pid, cid = approved_story(env)
    be = P2BFake()
    p = written_plan(cid, be)
    from story import db
    db.ex("UPDATE plans SET format='9:16' WHERE id=?", (p["id"],))
    asyncio.run(storyboard.make_storyboard(p["id"], be))
    imgplan.compile_plan(p["id"])
    c = storyboard.get_scenes(p["id"])[0]["data"]["prompts"]
    for a in ("qwen", "flux"):
        assert c[a]["size"] == {"width": 768, "height": 1344} and "tall vertical 9:16" in c[a]["prompt"] and "bottom 20 percent" in c[a]["prompt"]
    assert providers.snap(4000, 3000, providers.get("qwen-image-2.1"))[2] is True                  # oversize is snapped into the pixel budget


class FakeResp:
    status_code = 200

    def __init__(self, seed=7):
        self._seed = seed

    def json(self):
        return {"data": [{"b64_json": base64.b64encode(b"\x89PNG-fake").decode(), "seed": self._seed, "width": 1344, "height": 768, "revised_prompt": ""}]}


def test_preview_is_off_by_default_explicit_and_records_everything(env, monkeypatch):
    import httpx
    sent = {}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, headers=None):
            sent.update(url=url, body=json)
            return FakeResp()
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    pid, scenes, _ = compiled(env)
    sid = scenes[0]["id"]
    with pytest.raises(planner.PlanError):
        asyncio.run(imgplan.preview(sid, "qwen"))                                                     # switched off by default
    imgplan.set_image_models(pid, {"previews_enabled": True})
    rec = asyncio.run(imgplan.preview(sid, "flux", seed=7, backend_settings={"base_url": "http://x/v1"}, key="k"))
    assert sent["url"] == "http://x/v1/images/generations" and sent["body"]["model"] == "flux2-klein-9b" and sent["body"]["negative_prompt"]
    assert sent["body"]["size"] == "1344x768" and "steps" not in sent["body"] and "cfg" not in sent["body"]  # the gateway's tuned defaults are not overridden
    assert rec["model"] == "flux2-klein-9b" and rec["prompt"] == scenes[0]["data"]["prompts"]["flux"]["prompt"] and rec["seed"] == 7
    assert (imgplan.preview_dir(pid) / rec["file"]).read_bytes().startswith(b"\x89PNG")
    saved = storyboard.get_scene(sid)["data"]["previews"]
    assert len(saved) == 1 and saved[0]["request"]["n"] == 1
    imgplan.rate_preview(sid, rec["id"], {"composition": 4, "note": "good", "ignored": 1})
    assert storyboard.get_scene(sid)["data"]["previews"][0]["rating"] == {"composition": 4, "note": "good"}
    with pytest.raises(planner.PlanError):
        storyboard.edit_scene(sid, {"previews": []})


def test_compile_does_not_touch_approved_or_locked_scene_content(env):
    _pid, cid, be, p = boarded(env)
    pid = p["id"]
    sid = p["scenes"][0]["id"]
    storyboard.edit_scene(sid, {"status": "approved"})
    storyboard.edit_scene(sid, {"locked": True})
    before = storyboard.get_scene(sid)
    imgplan.compile_plan(pid)
    after = storyboard.get_scene(sid)
    assert after["status"] == "approved" and after["locked"]
    strip = lambda d: {k: v for k, v in d.items() if k not in ("prompts", "adapters")}  # noqa: E731
    assert strip(after["data"]) == strip(before["data"])


def test_api_round_trip(tmp_path, monkeypatch):
    import config
    from fastapi.testclient import TestClient
    import main
    from story import projects, review
    from story2 import jobs
    from test_phase2a import make_book, run
    from fakellm import FakeBackend
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        r = c.get("/api/plans/providers")
        assert r.status_code == 200 and [p["id"] for p in r.json()["providers"]] == ["qwen-image-2.1", "flux2-klein-9b"]
        pid = projects.import_text(make_book(3, 8))
        run(pid, FakeBackend())
        cid = review.list_candidates(pid)[0]["id"]
        review.update_candidate(cid, {"status": "approved"})
        plan = c.post("/api/plans", json={"candidate_id": cid}).json()
        assert c.post(f"/api/plans/{plan['id']}/compile-prompts").status_code == 400                # no storyboard yet
        assert c.patch(f"/api/plans/{plan['id']}/image-models", json={"default": "nope"}).status_code == 400
        assert c.patch(f"/api/plans/{plan['id']}/image-models", json={"previews_enabled": True}).status_code == 200
        assert c.get("/api/plans/previews/x/..%2Fsecret").status_code == 404


def test_plates_never_describe_the_chart_and_keep_an_overlay_spec(env):
    over = {**FACTS_CHART, "subject": "a stock chart", "action": "the green line rises at a steep 45-degree angle", "exclusions": ["No logos"],
            "text_on_screen": [{"text": "seventeen percent drop", "placement": "top"}]}
    pid, scenes, rep = compiled(env, scene_over=over)
    for a in ("qwen", "flux"):
        c = scenes[0]["data"]["prompts"][a]
        assert "green line" not in c["prompt"] and "stock chart" not in c["prompt"]                    # the image model is never asked to draw the data
        assert c["overlay"]["shows"].startswith("the green line") and c["overlay"]["text"][0]["text"] == "seventeen percent drop"
    assert "must not appear: logos" in scenes[0]["data"]["prompts"]["qwen"]["prompt"].lower()           # "No logos" is not doubled into "must not appear: No logos"
    assert not [i for i in rep["issues"] if i["level"] == "error"], rep["issues"]


def test_only_factual_looking_numbers_are_checked(env):
    pid, scenes, _ = compiled(env)
    sc, assets = scenes[0], storyboard.get_assets(pid)
    base = sc["data"]["prompts"]["qwen"]
    ok = dict(base, prompt=base["prompt"] + " A 45-degree angle, 3D depth, 2D graphics.")
    assert not any(i["kind"] == "number" for i in imgprompts.validate_prompt(ok, sc, assets, "", None))
    bad = dict(base, prompt=base["prompt"] + " The stock fell 17% and 4321 shares traded.")
    assert sum(i["kind"] == "number" for i in imgprompts.validate_prompt(bad, sc, assets, "", None)) == 2
