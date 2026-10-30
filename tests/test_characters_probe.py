"""C0 probe helpers: the prompts and the summary (no gateway)."""
from characters import probe


def test_edit_prompts_keep_the_person_and_the_summary_averages():
    assert all("same" in text.lower() for _src, text in probe.EDITS.values())
    assert "head and shoulders" in probe.base_prompt("portrait").lower() and "Full body" in probe.base_prompt("body")
    rows = [{"ok": True, "kind": "edit_1ref", "seconds": 40, "identity": {"score": 8}}, {"ok": True, "kind": "edit_1ref", "seconds": 60, "identity": {"score": 6}},
            {"ok": False, "kind": "edit_1ref", "error": "x"}, {"ok": True, "kind": "generate_place", "seconds": 30}]
    out = probe.summarise(rows)
    assert out == {"seconds": {"edit_1ref": 50.0, "generate_place": 30.0}, "identity": {"edit_1ref": 7.0}}
