"""Short Ideas parking lot — generate, rate, approve, condition, queue.

Flow: pending → approved → conditioned → queued (short created) | rejected
"""
import hashlib
import re
from datetime import datetime

from story import db, llm as llm_mod, settings as settings_mod
from story.schemas import M, Str

from feedback import features as fb_features

SCHEMA = """
CREATE TABLE IF NOT EXISTS short_ideas(
  id TEXT PRIMARY KEY,
  title TEXT DEFAULT '',
  hook TEXT DEFAULT '',
  mechanisms TEXT DEFAULT '[]',
  premise TEXT DEFAULT '',
  why_works TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  engagement_score REAL DEFAULT 0,
  score_breakdown TEXT DEFAULT '{}',
  conditioning TEXT DEFAULT '{}',
  short_id TEXT DEFAULT '',
  created_at REAL,
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS idea_config(
  id INTEGER PRIMARY KEY CHECK(id=1),
  data TEXT DEFAULT '{}'
);
"""

# Columns added after the first release (ensure() adds them to an older database).
EXTRA_COLUMNS = {"sources": "TEXT DEFAULT '[]'", "dup_of": "TEXT DEFAULT ''", "reject_reason": "TEXT DEFAULT ''", "style": "TEXT DEFAULT ''", "reviewed": "INTEGER DEFAULT 0", "auto": "INTEGER DEFAULT 0", "cond_fails": "INTEGER DEFAULT 0", "territory": "TEXT DEFAULT ''", "territory_src": "TEXT DEFAULT ''", "origin": "TEXT DEFAULT ''", "approved_at": "REAL DEFAULT 0", "conditioned_at": "REAL DEFAULT 0", "done_at": "REAL DEFAULT 0"}

BRIGHT_STYLES = ("realism", "pixar3d", "anime", "ghibli", "tinyworld")        # ticked until the person chooses; the dark styles (noir, cyberpunk) are opt-in
MAX_COND_FAILS = 2                                                           # an idea whose brief failed this many times is left alone by the autopilot

# What the Ideas screen keeps between visits and what the unattended auto-queue uses. Saved in the database, so any browser and the server see the same.
CONFIG_DEFAULTS = {
    "autorun": False, "diverse": False, "n": 7, "min_score": 7.0,
    "autopilot": False,                              # the master switch: OFF = nothing runs by itself, whatever the switches below say
    "styles": list(BRIGHT_STYLES),                                   # picture styles the ideas may use (empty = any); the queue picks from these only
    "auto_generate": False, "auto_approve": False, "auto_condition": False,
    "gen_every_h": 1.0, "gen_n": 5, "approve_min": 7.8, "make_every_h": 2.0, "pending_cap": 30, "planning_cap": 3,
    "next_gen_at": 0.0, "next_make_at": 0.0,         # when the next hourly batch and the next short are due (kept here so a restart keeps the schedule)
    "use_playbook": True, "explore": 0.35, "auto_feedback": False, "playbook_min_new": 3,       # the channel's results steer the factory only through an APPROVED Playbook (docs/PLAN_feedback_loop.md)
    "tone_arms": ["bigbro", "explorer", "storyteller", "viral", "thriller"],
    "run": {"pipeline": "keyframe", "voice": "taksh_hn", "language": "hi", "target_s": 30, "tone_id": "bigbro", "edge": "clean", "upscale": "2k", "clip_quality": "opening", "words_lo": "", "words_hi": "", "tempo_max": ""},
}

MECHANISMS = [
    "curiosity_gap", "threat_detection", "novelty", "prediction_error",
    "social_comparison", "pattern_interruption", "emotional_arousal", "incomplete_loops",
]

# ── Pydantic schemas ──────────────────────────────────────────────────────────

class _IdeaSpec(M):
    title:      Str       = ""
    hook:       Str       = ""
    mechanisms: list[str] = []
    premise:    Str       = ""
    why_works:  Str       = ""
    sources:    list[int] = []
    territory:  Str       = ""


class _IdeasBatch(M):
    ideas: list[_IdeaSpec] = []


class _ScoreSpec(M):
    id:                     Str   = ""
    hook_strength:          float = 0
    mechanism_count:        int   = 0
    emotional_intensity:    float = 0
    completion_rate:        float = 0
    novelty:                float = 0
    progressive_revelation: float = 0
    shareability:           float = 0
    engagement_score:       float = 0
    reasoning:              Str   = ""
    verdict:                Str   = ""


class _ScoreBatch(M):
    scores: list[_ScoreSpec] = []


class _Conditioning(M):
    refined_hook:      Str       = ""
    key_facts:         list[str] = []
    visual_direction:  Str       = ""
    suggested_tone:    Str       = ""


class _ConditionResult(M):
    conditioning: _Conditioning = _Conditioning()


# ── prompts ───────────────────────────────────────────────────────────────────

_FRAMEWORK = """\
═══════════════════════════════════════════════════════════════════
THE HUMAN ATTENTION ENGINE — SHORT VIDEO IDEA FRAMEWORK
═══════════════════════════════════════════════════════════════════

CORE PHILOSOPHY
───────────────
We are NOT selling information. We are creating a psychological NEED to discover the answer.
This is the most important distinction. Violating it produces ideas that perform poorly.

THE BAD vs GOOD TEST — apply this to every single idea before accepting it:

  BAD (information selling — these fail):
    ✗ "India's military strength"
    ✗ "How AI is changing the world"
    ✗ "India's economic growth"
    ✗ "The history of the Mughal Empire"
    ✗ "Why exercise is important"

  GOOD (psychological need creation — these win):
    ✓ "What happens if an invisible enemy can shut down India's entire power grid?"
    ✓ "Why can a tiny ant carry something 50 times its body weight, but humans cannot?"
    ✓ "Why does the world's most powerful army fear fighting in the Himalayas?"
    ✓ "What if humans suddenly stopped needing sleep?"
    ✓ "Why can a country have billions of dollars but still struggle to feed its people?"
    ✓ "The one decision that made India lose 10,000 square kilometres of land — and nobody talks about it."
    ✓ "What is the one thing America cannot buy that India has for free?"

THE DIFFERENCE: A BAD hook names a subject. A GOOD hook creates an open question
the brain MUST resolve. The viewer feels compelled to keep watching.

═══════════════════════════════════════════════════════════════════
THE 8 ATTENTION MECHANISMS
═══════════════════════════════════════════════════════════════════

Every idea must trigger at least 2. Three or more preferred. Be specific about WHICH fire.

1. CURIOSITY GAP
   What it exploits: The brain's need to resolve uncertainty — an open question feels like
   an itch the mind cannot stop scratching until it is answered.
   How to trigger: Reveal an unbelievable or counterintuitive question. Delay the answer.
   Make the viewer feel they CANNOT skip because the answer will change something for them.
   Example: "Why does the world's most advanced stealth fighter refuse to fly in rain?"

2. THREAT DETECTION
   What it exploits: The amygdala's hair-trigger threat-scanning circuit. Humans are hardwired
   to freeze and pay full attention when danger signals appear — this is primal, not rational.
   How to trigger: Hidden threats, national security risks, survival scenarios, things that
   could hurt us, our country, our finances, our health, our children.
   Example: "The silent virus that wiped out 7 Indian cities — and nobody saw it coming."

3. NOVELTY
   What it exploits: The dopamine reward from encountering something genuinely unfamiliar.
   Not "new" in a marketing sense. The viewer must think: "I never knew this existed."
   How to trigger: A fact, place, technology or scenario the viewer has never encountered.
   Must be genuinely conceptually unfamiliar, not just a new angle on a known topic.
   Example: "The abandoned city under India's largest lake that nobody is allowed to visit."

4. PREDICTION ERROR
   What it exploits: The brain HATES outcomes it did not predict. Cognitive dissonance creates
   compulsive engagement — the mind must resolve the contradiction.
   How to trigger: Build a clear expectation in the opening sentence. Then violently break it.
   The viewer believes they know what will happen next — and they are completely wrong.
   Example: "The country with the world's smallest army just defeated the largest one. Here is how."

5. SOCIAL COMPARISON
   What it exploits: Status anxiety and tribal belonging — primal motivators that never switch off.
   The viewer instinctively asks: "Where do I / my country / my group stand in this?"
   How to trigger: India vs USA, rich vs poor, powerful vs weak, ancient vs modern, us vs them.
   Forces the viewer to position themselves in the comparison.
   Example: "Why does a worker in Germany earn 40 times more than the same worker in India for identical work?"

6. PATTERN INTERRUPTION
   What it exploits: The brain is a prediction machine. It constantly forecasts what comes next.
   An unexpected break in pattern fires attention neurons involuntarily — the brain cannot ignore it.
   How to trigger: An opening that breaks the expected format, a visual or narrative shift,
   a fact that completely breaks the viewer's mental model of a familiar subject.
   Example: "The hospital that kills more patients than it saves — and it is completely intentional."

7. EMOTIONAL AROUSAL
   What it exploits: Strong emotions create deep memories and drive social sharing.
   An emotionally flat short is forgotten in seconds. An emotionally charged one is shared.
   Target emotions: Awe (scale/power), Fear (threat/danger), National pride (India's strength),
   Righteous anger (injustice/betrayal), Genuine surprise (the impossible made real).
   How to trigger: Identify the PEAK emotional moment. Design the entire narrative to build
   toward that moment. Everything before is preparation. The peak arrives at second 25.
   Example: "The 23-year-old Indian scientist who solved the problem that broke NASA for 60 years."

8. INCOMPLETE LOOPS
   What it exploits: The Zeigarnik Effect — the brain obsessively rehearses unfinished tasks.
   An open narrative loop is psychologically uncomfortable until it is closed.
   How to trigger: Introduce a mystery at the very first second. Drop clues progressively.
   The answer arrives at the END. Never close the loop early.
   Example: "Someone is stealing billions from India every year. The government knows who. And they are doing nothing."

═══════════════════════════════════════════════════════════════════
DESIGN PRINCIPLES FOR WINNING IDEAS
═══════════════════════════════════════════════════════════════════

1. OPENING URGENCY: The hook must feel urgent. The viewer must believe the answer will
   change something for them personally — their safety, understanding, pride, or worldview.

2. PROGRESSIVE REVELATION: Every 3-5 seconds, new information must change the viewer's
   understanding of what they are watching. The short must escalate continuously.

3. DELAYED PEAK: The strongest revelation, the most shocking fact, the biggest twist —
   it goes at second 25-30, not in the first 10 seconds.

4. MENTAL AFTERSHOCK: The final moment must make the viewer rethink the opening or
   want to immediately share or discuss the subject.

5. TRUTH ONLY: Never fabricate danger, never use misinformation, never invent facts.
   The psychological power must come from REAL, verifiable information.

═══════════════════════════════════════════════════════════════════
BEST SUBJECT TERRITORIES
═══════════════════════════════════════════════════════════════════

Military technology and strategy | Neuroscience and human behaviour | Geopolitics and power
Economic paradoxes and inequality | Historical revelations and cover-ups | Extreme engineering
India's hidden capabilities and failures | Science of everyday phenomena | Impossible scenarios
Space and civilisation scale | Medical and biological mysteries | Financial systems and control"""


TERRITORY_IDS = ", ".join(fb_features.TERRITORIES)


def _generate_system() -> str:
    return _GENERATE_SYSTEM.replace("__TERRITORIES__", TERRITORY_IDS)


_GENERATE_SYSTEM = _FRAMEWORK + """

═══════════════════════════════════════════════════════════════════
YOUR TASK: GENERATE SHORT VIDEO IDEAS
═══════════════════════════════════════════════════════════════════

You are a world-class short-video idea generator trained on the Human Attention Engine framework above.
Every idea you generate must pass the BAD vs GOOD test before you include it.

MANDATORY RULES — a rejected idea violates one of these:
  R1. The hook is a question or shock statement — NEVER a topic title.
  R2. The hook creates a psychological NEED to discover the answer, not an interest in a subject.
  R3. At least 2 of the 8 mechanisms fire. Three or more preferred.
  R4. No two ideas use the same primary mechanism combination.
  R5. The idea is based on real, verifiable facts. No fabricated danger.
  R6. Subject areas are diverse across the batch — not all military, not all history.

SELF-CHECK BEFORE RETURNING EACH IDEA:
  → Is the hook a question or shock statement (not a topic)?
  → Would a viewer who was mid-scroll STOP and feel they MUST watch?
  → Does it trigger at least 2 mechanisms genuinely (not marginally)?
  → Is it different from every other idea in this batch?
  If any answer is NO — rewrite the idea until all answers are YES.

OUTPUT FORMAT — return valid JSON only, no explanation, no commentary:
{
  "ideas": [
    {
      "title": "Short display title — 5 to 8 words max",
      "hook": "The exact opening question or shock statement. This IS the idea. Max 20 words. Must be a question (?) or shock statement — never a topic label.",
      "mechanisms": ["list", "of", "mechanism_ids"],
      "premise": "2-3 sentences. What this short actually covers. What the viewer learns beat by beat. What the reveal at the end is. Write it like a producer's one-paragraph brief.",
      "why_works": "4-6 sentences. Analyse specifically which attention triggers fire and WHY this particular subject activates them psychologically. Be analytical, not promotional.",
      "territory": "the subject territory, exactly one of: __TERRITORIES__"
    }
  ]
}

Mechanism IDs must be from exactly this list:
curiosity_gap, threat_detection, novelty, prediction_error, social_comparison,
pattern_interruption, emotional_arousal, incomplete_loops"""


_RATE_SYSTEM = _FRAMEWORK + """

═══════════════════════════════════════════════════════════════════
YOUR TASK: SCORE IDEAS AS A YOUTUBE SHORTS ENGAGEMENT ANALYST
═══════════════════════════════════════════════════════════════════

You are an expert YouTube Shorts performance analyst. Score each idea on 7 engagement dimensions.
Be calibrated: a mediocre hook should score 4-5, not 7-8. Reserve 9-10 for exceptional work.

SCORING DIMENSIONS:

1. hook_strength (1-10)
   How irresistible is the opening question or statement?
   10 = the viewer would stop scrolling mid-motion and feel physically unable to continue without watching.
   7  = strong, would stop many viewers.
   5  = interesting but not urgent — curiosity without compulsion.
   3  = sounds like a documentary title.
   1  = sounds like a Wikipedia article heading.

2. mechanism_count (integer 0-8)
   How many of the 8 attention mechanisms does this genuinely, strongly trigger?
   Count only mechanisms that are powerfully activated. Do not count marginal activations.

3. emotional_intensity (1-10)
   How powerful is the peak emotional moment designed into this idea?
   What emotion does it target? How strongly will the average Indian viewer feel it?
   10 = the viewer feels something physically (goosebumps, stomach drop, chest tightening).
   5  = engaged but not moved.
   1  = no emotional charge.

4. completion_rate (1-10)
   How likely is a viewer to watch all 30 seconds without pausing or skipping?
   Consider: does the structure naturally delay the payoff?
   Are there 3-5 second revelation beats built into the premise?
   10 = the viewer is structurally unable to leave — the incomplete loop forces them to stay.
   5  = will hold most viewers who started.
   1  = no structural reason to stay past 10 seconds.

5. novelty (1-10)
   How fresh and unexplored is this specific angle?
   10 = this exact angle has never appeared in a popular Indian short.
   7  = fresh take on a known subject.
   5  = somewhat familiar territory.
   1  = done to death.

6. progressive_revelation (1-10)
   Does this idea naturally support new information every 3-5 seconds that changes understanding?
   10 = the structure practically writes itself with escalating reveals.
   5  = some natural beats but requires effort.
   1  = one-beat idea that reveals everything immediately.

7. shareability (1-10)
   Would a viewer immediately forward this to someone specific in their life?
   10 = "I have to send this to 5 people right now — they need to see this."
   5  = "I might share this if it's really well made."
   1  = "I'll watch it and forget it."

COMPOSITE ENGAGEMENT SCORE (calculate exactly using this formula):
  score = (hook_strength × 0.25) + (mechanism_count/8 × 10 × 0.20) +
          (emotional_intensity × 0.15) + (completion_rate × 0.15) +
          (novelty × 0.10) + (progressive_revelation × 0.10) + (shareability × 0.05)

COMPARATIVE CALIBRATION: After scoring individually, review all scores together.
Adjust so the distribution reflects genuine relative quality — the best idea should be
meaningfully higher than the worst. Do not cluster all scores at 7.

OUTPUT FORMAT — return valid JSON only:
{
  "scores": [
    {
      "id": "exact idea id passed to you",
      "hook_strength": 8,
      "mechanism_count": 4,
      "emotional_intensity": 7,
      "completion_rate": 8,
      "novelty": 6,
      "progressive_revelation": 7,
      "shareability": 6,
      "engagement_score": 7.35,
      "reasoning": "Analytical paragraph — 4-6 sentences. What specifically makes this idea strong or weak? Which mechanisms fire and how powerfully? What is the structural strength or the structural flaw? Be specific and critical.",
      "verdict": "One punchy sentence: why this will win or lose the first 3 seconds of the scroll."
    }
  ]
}"""


_CONDITION_SYSTEM = """\
You are a senior short-video producer handing an approved idea to the script writers' room.
Your job is to sharpen the idea and hand over the CONCEPT only. The writers' room (story bible, retention map, beat drafts, punch-up) decides the structure, the beats, the timing, the emotions, the cast and every spoken line. Do NOT plan any of that.

CRITICAL RULE — SHARPEN, NEVER SANITISE:
You are making the idea MORE psychologically powerful, not softening it into a topic description.
The refined concept must be harder-hitting than the input. If you flatten it, you have failed.

═══════════════════════════════════════════════════════════════════
CONCEPT REQUIREMENTS
═══════════════════════════════════════════════════════════════════

1. REFINED HOOK (required)
   The angle of the short: the one claim, question or contradiction that makes a viewer stop mid-scroll.
   It is the angle, not the spoken line: the writers decide the exact words.
   Rules:
   - Maximum 15 words.
   - Must trigger the stated attention mechanisms harder than the original.
   - Must be a question (?) or a shock statement. Never a topic label.

2. KEY FACTS (3-5 items)
   Specific, verifiable facts that anchor the story. The writers may invent atmosphere but must not invent facts, so these are what they can rely on.
   Rules:
   - Each fact must be specific enough to verify independently.
   - Bad: "India has a large military." Good: "India's mountain warfare corps operates at Siachen at 22,000 feet — the highest active battlefield on Earth."
   - No invented statistics. No approximated numbers presented as exact.

3. VISUAL DIRECTION
   One clear sentence for the image model and director.
   Include: the picture style, colour palette, lighting mood. Scenes are bright and evenly lit by default; go dark only when the idea itself is about darkness.
   Example: "Realism — bright natural daylight, clean warm palette, documentary handheld feel."

4. SUGGESTED TONE
   Pick exactly ONE from this list: storyteller, soothing, documentary, bigbro, explorer, thriller, roaster
   Follow with one sentence explaining why this tone amplifies the specific emotional triggers of this idea.

Do not write an arc, beats, timings, an emotional journey, an opening line or shot notes.

OUTPUT FORMAT — return valid JSON only, no explanation outside the JSON:
{
  "conditioning": {
    "refined_hook": "...",
    "key_facts": ["...", "...", "..."],
    "visual_direction": "...",
    "suggested_tone": "..."
  }
}"""


# ── CRUD ──────────────────────────────────────────────────────────────────────


def ensure() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)
        have = {r[1] for r in c.execute("PRAGMA table_info(short_ideas)")}
        for col, ddl in EXTRA_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE short_ideas ADD COLUMN {col} {ddl}")


def _load(r: dict | None) -> dict | None:
    if r is None:
        return None
    r = dict(r)
    r["mechanisms"]     = db.jload(r.get("mechanisms"), [])
    r["score_breakdown"] = db.jload(r.get("score_breakdown"), {})
    r["conditioning"]   = db.jload(r.get("conditioning"), {})
    r["sources"]        = db.jload(r.get("sources"), [])
    return r


def get_config() -> dict:
    ensure()
    saved = db.jload((db.one("SELECT data FROM idea_config WHERE id=1") or {}).get("data"), {})
    return {**CONFIG_DEFAULTS, **saved, "run": {**CONFIG_DEFAULTS["run"], **(saved.get("run") or {})}}


def save_config(patch: dict) -> dict:
    """Merge `patch` into the saved config; unknown keys are ignored and values are coerced to their type."""
    cur = get_config()
    if "autorun" in patch:
        cur["autorun"] = bool(patch["autorun"])
    if "diverse" in patch:
        cur["diverse"] = bool(patch["diverse"])
    if "n" in patch:
        cur["n"] = max(1, min(15, int(patch["n"] or 7)))
    if "min_score" in patch:
        cur["min_score"] = max(0.0, min(10.0, float(patch["min_score"] or 0)))
    for k in ("autopilot", "auto_generate", "auto_approve", "auto_condition", "use_playbook", "auto_feedback"):
        if k in patch:
            cur[k] = bool(patch[k])
    for k, lo, hi in (("gen_every_h", 0.25, 48), ("make_every_h", 0.25, 48), ("approve_min", 0, 10)):
        if k in patch:
            cur[k] = max(lo, min(hi, float(patch[k] or lo)))
    for k, lo, hi in (("gen_n", 1, 15), ("pending_cap", 1, 500), ("planning_cap", 1, 50)):
        if k in patch:
            cur[k] = max(lo, min(hi, int(patch[k] if patch[k] not in (None, "") else lo)))
    if "explore" in patch:
        cur["explore"] = max(0.3, min(0.4, float(patch["explore"]) if patch["explore"] not in (None, "") else 0.35))                # the owner wants 30 to 40 % of choices to try something new
    if "playbook_min_new" in patch:
        cur["playbook_min_new"] = max(1, min(50, int(patch["playbook_min_new"] or 3)))
    if "tone_arms" in patch:
        from . import tones
        cur["tone_arms"] = [x for x in dict.fromkeys(patch["tone_arms"] or []) if x in tones.TONES]
    if "styles" in patch:
        from . import looks
        cur["styles"] = [x for x in dict.fromkeys(patch["styles"] or []) if x in looks.presets()]
    for k, v in (patch.get("run") or {}).items():
        if k in CONFIG_DEFAULTS["run"]:
            if k == "target_s":
                cur["run"][k] = max(5, min(180, int(float(v or 30))))
            elif k in ("words_lo", "words_hi"):
                cur["run"][k] = str(max(3, min(1000, int(float(v)))) ) if str(v or "").strip() not in ("", "0") else ""
            elif k == "tempo_max":
                cur["run"][k] = f"{max(1.0, min(1.6, float(v))):g}" if str(v or "").strip() not in ("", "0") else ""
            elif k == "clip_quality":
                cur["run"][k] = v if v in ("opening", "full", "fast") else "opening"
            else:
                cur["run"][k] = "" if v is None else str(v)
    with db.tx() as c:
        c.execute("INSERT INTO idea_config(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (db.jdump(cur),))
    return cur


def set_state(**kw) -> None:
    """Write schedule values (next_gen_at, next_make_at) without touching what the screen saved."""
    cur = get_config()
    cur.update({k: v for k, v in kw.items() if k in ("next_gen_at", "next_make_at")})
    with db.tx() as c:
        c.execute("INSERT INTO idea_config(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (db.jdump(cur),))


def counts() -> dict:
    ensure()
    out = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM short_ideas GROUP BY status")}
    return out


def mark_reviewed(idea_id: str, reviewed: bool = True) -> dict:
    get(idea_id)
    db.ex("UPDATE short_ideas SET reviewed=?, updated_at=? WHERE id=?", (1 if reviewed else 0, db.now(), idea_id))
    return get(idea_id)


def next_to_condition() -> dict | None:
    """The best approved idea that has no brief yet and has not failed too often."""
    return next((i for i in order(listing("approved")) if (i.get("cond_fails") or 0) < MAX_COND_FAILS), None)


def bump_cond_fail(idea_id: str) -> None:
    ensure()
    db.ex("UPDATE short_ideas SET cond_fails=COALESCE(cond_fails,0)+1, updated_at=? WHERE id=?", (db.now(), idea_id))


def order(items: list[dict]) -> list[dict]:
    """The one order every stage is taken in: best score first, the one waiting longest first among equals. The pickers and the screen both use it, so the screen shows what will happen."""
    return sorted(items, key=lambda i: (-(i.get("engagement_score") or 0), i["created_at"]))


def queues(min_score: float = 0.0, limit: int = 30) -> dict:
    """The ideas in each stage in the order the autopilot takes them. `rank` is the place in line (1 = next); an idea the autopilot will not take (brief failed twice, score under `min_score`) has no rank and carries `hold` (why), and sits after the ranked ones."""
    def line(status, held):
        ranked, left = [], []
        for i in order(listing(status)):
            why = held(i)
            (left if why else ranked).append({**i, "hold": why})
        for n, i in enumerate(ranked, 1):
            i["rank"] = n
        return (ranked + left)[:limit]
    return {
        "approved": line("approved", lambda i: f"brief failed {i['cond_fails']} times: skipped" if (i.get("cond_fails") or 0) >= MAX_COND_FAILS else ""),
        "conditioned": line("conditioned", lambda i: f"score {(i.get('engagement_score') or 0):.1f} is under {min_score:g}: not taken automatically" if (i.get("engagement_score") or 0) < min_score else ""),
        "queued": sorted(listing("queued"), key=lambda i: -i["updated_at"])[:limit],
        "done": sorted(listing("done"), key=lambda i: -(i.get("done_at") or i["updated_at"]))[:limit],
    }


def auto_approve(min_score: float) -> list[str]:
    """Approve every scored pending idea at or above `min_score`. Returns the ids."""
    ids = [i["id"] for i in listing("pending") if (i.get("engagement_score") or 0) >= min_score]
    for i in ids:
        set_status(i, "approved")
        db.ex("UPDATE short_ideas SET auto=1 WHERE id=?", (i,))
    return ids


def style_choice(allowed: list[str], direction: str) -> tuple[str, str]:
    """(style, how it was chosen): `idea` when the idea's own visual direction names an allowed style, `exploit` or `explore` when the Playbook's bandit chose, else `rotation`.
    The picture style for a short: only from `allowed` (the Ideas config). The idea's own visual direction wins when it names an allowed style; otherwise the allowed style used least
    so far, so styles rotate. No allowed styles = '' (the caller falls back to matching the direction against every style)."""
    allowed = [x for x in allowed if x]
    if not allowed:
        return "", "idea"
    d = (direction or "").lower()
    for sid in allowed:
        if re.search(rf"\b{re.escape(sid)}\b", d):
            return sid, "idea"
    try:
        from feedback import bandit
        chosen = bandit.choose_style(allowed)
    except Exception as e:  # noqa: BLE001 - the feedback loop must never stop a short from being made
        print(f"[feedback] style bandit failed: {e}", flush=True)
        chosen = None
    if chosen:
        return chosen
    ensure()
    used = {r["style"]: r["n"] for r in db.q("SELECT style, COUNT(*) n FROM short_ideas WHERE style<>'' GROUP BY style")}
    return min(allowed, key=lambda x: (used.get(x, 0), allowed.index(x))), "rotation"


def pick_style(allowed: list[str], direction: str) -> str:
    return style_choice(allowed, direction)[0]


def _plan_sources(sink: list) -> None:
    """Match the ideas written to the slots of the territory plan (how each territory was chosen)."""
    try:
        from feedback import bandit
        bandit.assign_sources([i["id"] for i in sink])
    except Exception as e:  # noqa: BLE001
        print(f"[feedback] plan sources failed: {e}", flush=True)


def feedback_extra(n: int, lenses: bool = False) -> str:
    """The approved Playbook's learnings and the territory plan of this batch (empty until a Playbook is approved)."""
    try:
        from feedback import bandit, playbook
        if not playbook.enabled():
            return ""
        return "\n\n".join(x for x in (playbook.learnings_block("idea"), bandit.territory_block(n, lenses)) if x)
    except Exception as e:  # noqa: BLE001
        print(f"[feedback] learnings failed: {e}", flush=True)
        return ""


def next_for_autoqueue(min_score: float) -> dict | None:
    """The best conditioned idea that is good enough and not queued yet (highest score first)."""
    return next((i for i in order(listing("conditioned")) if (i.get("engagement_score") or 0) >= min_score), None)


def add(title: str, hook: str, mechanisms: list, premise: str, why_works: str, sources: list | None = None, territory: str = "", origin: str = "") -> dict:
    ensure()
    iid = f"idea-{hashlib.sha1(f'{hook}{db.now()}'.encode()).hexdigest()[:8]}"
    db.ex(
        "INSERT INTO short_ideas(id,title,hook,mechanisms,premise,why_works,status,sources,created_at,updated_at,territory,origin)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (iid, title, hook, db.jdump(mechanisms), premise, why_works, "pending", db.jdump(sources or []), db.now(), db.now(), fb_features.territory_of(territory), origin),
    )
    return get(iid)


# ── Duplicates: the same context as an idea already seen (any status) is rejected before it is scored ──

_STOP = set("a an the of to in on at is are was were be been being it its this that these those and or but for from with by as if than then so do does did how why what who whom which when where can could would should will "
            "may might must you your we our us they them their he she his her i me my not no yes more most less very just into over under out up down about after before again ever never one two".split())
SIMILAR_SURE = 0.55          # word overlap (Jaccard) that is a duplicate without asking the model
SIMILAR_ASK = 0.08           # from here the model is asked (measured on title, hook and the start of the premise, so a paraphrase still comes close)


def _words(x: dict, deep: bool = False) -> set[str]:
    text = re.sub(r"[^a-z0-9 ]+", " ", f"{x.get('title', '')} {x.get('hook', '')}{(' ' + (x.get('premise') or '')[:220]) if deep else ''}".lower())
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in text.split() if len(w) > 2 and w not in _STOP}


def similarity(a: dict, b: dict, deep: bool = False) -> float:
    wa, wb = _words(a, deep), _words(b, deep)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class _DupSpec(M):
    id:      Str = ""
    same_as: Str = ""
    why:     Str = ""


class _DupBatch(M):
    results: list[_DupSpec] = []


_DUP_SYSTEM = """You compare new short-video ideas with ideas already seen. Two ideas are the SAME CONTEXT when they would make essentially the same short: the same event, fact, mystery or question, even if worded differently. \
A different angle or a different example inside the same broad field is NOT the same. Be strict only about real repeats.
Return ONLY JSON: {"results": [{"id": "the new idea id", "same_as": "the id of the earlier idea it repeats, or empty", "why": "one short sentence"}]} with one entry for every new idea."""


def reject_duplicate(idea_id: str, dup_of: str, why: str) -> dict:
    ensure()
    db.ex("UPDATE short_ideas SET status='rejected', dup_of=?, reject_reason=?, updated_at=? WHERE id=?", (dup_of, f"Duplicate: {why}"[:300], db.now(), idea_id))
    return get(idea_id)


async def dedup(new_ids: list[str], s: dict, key: str) -> list[str]:
    """Reject the new ideas that repeat an earlier idea (approved, rejected, queued, pending ... any) or an earlier one of the same batch. Returns the ids rejected. A word-overlap check settles
    the clear cases; the chat model judges the close ones, and if it fails only the clear cases are rejected."""
    new = [get(i) for i in new_ids]
    old = [i for i in listing() if i["id"] not in set(new_ids)]
    rejected: list[str] = []
    asks: list[tuple[dict, list[dict]]] = []
    pool = list(old)
    for idea in new:
        scored = sorted(((similarity(idea, o), o) for o in pool), key=lambda t: -t[0])
        if scored and scored[0][0] >= SIMILAR_SURE:
            reject_duplicate(idea["id"], scored[0][1]["id"], f"same as '{scored[0][1]['hook'][:80]}' ({scored[0][1]['status']})")
            rejected.append(idea["id"])
            continue
        deep = sorted(((similarity(idea, o, True), o) for o in pool), key=lambda t: -t[0])
        close = [o for sc, o in deep[:3] if sc >= SIMILAR_ASK]
        if close:
            asks.append((idea, close))
        pool.append(idea)
    if asks:
        try:
            backend = llm_mod.ChatBackend(s, key)
            caller = llm_mod.JsonCaller(backend, s)
            caller.last_attempt = True
            user = "NEW IDEAS, each with the earlier ideas that look close:\n" + "\n\n".join(
                f"NEW {i['id']}: {i['title']} - {i['hook']}\n  premise: {i['premise'][:240]}\n" + "\n".join(f"  EARLIER {o['id']} ({o['status']}): {o['title']} - {o['hook']}" for o in close) for i, close in asks)
            res = await caller.call(_DUP_SYSTEM, user, _DupBatch)
            valid = {o["id"] for _, close in asks for o in close}
            def full(x: str) -> str:                              # the model sometimes drops the "idea-" prefix of an id
                x = (x or "").strip()
                return x if not x or x.startswith("idea-") else "idea-" + x
            for r in res.value.results or []:
                rid, same = full(r.id), full(r.same_as)
                if same in valid and rid in {i["id"] for i, _ in asks} and rid not in rejected:
                    reject_duplicate(rid, same, r.why or "same context")
                    rejected.append(rid)
        except Exception as e:  # noqa: BLE001 - the clear cases are already handled
            print(f"[ideas] duplicate check failed: {e}", flush=True)
    return rejected


def avoid_text(limit: int = 60) -> str:
    """Topics already covered (rejected ones first), for the generator to stay away from."""
    rows = sorted(listing(), key=lambda i: (i["status"] != "rejected", -i["created_at"]))[:limit]
    return "\n".join(f"- {i['hook'][:110]}" for i in rows)


def get(idea_id: str) -> dict:
    ensure()
    r = _load(db.one("SELECT * FROM short_ideas WHERE id=?", (idea_id,)))
    if not r:
        raise ValueError(f"no such idea: {idea_id}")
    return r


def listing(status: str | None = None) -> list[dict]:
    ensure()
    rows = (
        db.q("SELECT * FROM short_ideas WHERE status=? ORDER BY created_at DESC", (status,))
        if status else
        db.q("SELECT * FROM short_ideas ORDER BY created_at DESC")
    )
    return [_load(r) for r in rows]


def set_status(idea_id: str, status: str, short_id: str = "") -> dict:
    ensure()
    if short_id:
        db.ex("UPDATE short_ideas SET status=?, short_id=?, updated_at=? WHERE id=?",
              (status, short_id, db.now(), idea_id))
    else:
        db.ex("UPDATE short_ideas SET status=?, updated_at=? WHERE id=?",
              (status, db.now(), idea_id))
    stamp = {"approved": "approved_at", "done": "done_at"}.get(status)         # when the idea qualified for the next stage, for "waiting since"
    if stamp:
        db.ex(f"UPDATE short_ideas SET {stamp}=? WHERE id=?", (db.now(), idea_id))
    return get(idea_id)


def finish_ready(is_made) -> list[str]:
    """A queued idea whose short is finished (`is_made(short_id)`) is done: no click needed. Returns the ids moved."""
    ids = [i["id"] for i in listing("queued") if i.get("short_id") and is_made(i["short_id"])]
    for i in ids:
        set_status(i, "done")
    return ids


def save_score(idea_id: str, score: float, breakdown: dict) -> dict:
    ensure()
    db.ex("UPDATE short_ideas SET engagement_score=?, score_breakdown=?, updated_at=? WHERE id=?",
          (score, db.jdump(breakdown), db.now(), idea_id))
    return get(idea_id)


def save_conditioning(idea_id: str, conditioning: dict) -> dict:
    ensure()
    db.ex("UPDATE short_ideas SET conditioning=?, status=?, cond_fails=0, updated_at=?, conditioned_at=? WHERE id=?",
          (db.jdump(conditioning), "conditioned", db.now(), db.now(), idea_id))
    return get(idea_id)


def delete_idea(idea_id: str) -> None:
    ensure()
    db.ex("DELETE FROM short_ideas WHERE id=?", (idea_id,))


# ── Diverse mode: 5 domain lenses rotated across sub-calls ───────────────────

_LENSES = [
    {
        "perspective": "strategic military and geopolitics analyst",
        "domains": (
            "military technology, national security strategy, geopolitical power shifts, "
            "historical battles and their hidden causes, border conflicts, weapons systems, "
            "intelligence failures, nuclear deterrence, proxy wars"
        ),
        "emphasis": "threat_detection, prediction_error, social_comparison",
    },
    {
        "perspective": "behavioural scientist and science communicator",
        "domains": (
            "human biology, neuroscience, evolutionary psychology, cognitive biases, "
            "medical mysteries, animal behaviour, the hidden science of everyday phenomena, "
            "how the human body defies expectation"
        ),
        "emphasis": "novelty, curiosity_gap, emotional_arousal",
    },
    {
        "perspective": "investigative economic journalist",
        "domains": (
            "economics, wealth concentration, financial system design, corporate power and abuse, "
            "market manipulation, poverty paradoxes, how money actually moves, "
            "economic policies with counterintuitive outcomes"
        ),
        "emphasis": "social_comparison, prediction_error, incomplete_loops",
    },
    {
        "perspective": "Indian history and cultural researcher",
        "domains": (
            "Indian history suppressed or overlooked, forgotten heroes and betrayals, "
            "cultural myths tested against reality, ancient Indian science and engineering, "
            "partition and independence era secrets, regional stories the mainstream ignores"
        ),
        "emphasis": "pattern_interruption, emotional_arousal, novelty",
    },
    {
        "perspective": "extreme engineering and space science explainer",
        "domains": (
            "extreme engineering feats and their hidden failures, space exploration and its paradoxes, "
            "physics at impossible scales, climate and ocean systems, deep infrastructure, "
            "the mathematics and engineering that keep civilisation alive"
        ),
        "emphasis": "novelty, curiosity_gap, pattern_interruption",
    },
]


def _date_context() -> str:
    now = datetime.now()
    return (
        f"TODAY'S DATE: {now.strftime('%B %d, %Y')} ({now.strftime('%A')})\n"
        "TEMPORAL RELEVANCE INSTRUCTIONS:\n"
        "  — Consider what subjects are naturally top-of-mind for Indian audiences THIS month.\n"
        "  — Think about seasonal relevance: festivals, cricket season, budget cycles, exam season,\n"
        "    monsoon/summer/winter impacts, harvest periods, school calendars.\n"
        "  — Consider global events, geopolitical developments, economic news cycles that\n"
        "    an Indian viewer would be discussing or searching right now.\n"
        "  — Evergreen ideas that work any time of year are acceptable, but ideas with\n"
        "    heightened relevance to THIS specific month have an advantage.\n"
        "  — Do NOT invent or fabricate news events. Use your knowledge of recurring\n"
        "    seasonal patterns and the general state of the world as of your training."
    )


def _lens_user_prompt(n: int, lens: dict, extra: str = "") -> str:
    return (
        f"Generate exactly {n} short video ideas following the Human Attention Engine framework.\n\n"
        f"{_date_context()}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"YOUR PERSPECTIVE FOR THIS BATCH: {lens['perspective'].upper()}\n"
        f"FOCUS EXCLUSIVELY ON: {lens['domains']}\n"
        f"PRIORITISE THESE MECHANISMS: {lens['emphasis']}\n"
        "Find the angle in this domain that the average viewer would NEVER expect.\n"
        "The ideas must be unmistakably rooted in this domain — do not drift.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{extra}\n\n"
        "HARD REQUIREMENTS:\n"
        f"  — Return exactly {n} ideas.\n"
        "  — Every hook is a question (?) or a shock statement. Never a topic.\n"
        "  — Every idea triggers at least 2 mechanisms. Aim for 3.\n"
        "  — All facts must be real and verifiable.\n\n"
        "FINAL SELF-CHECK — apply this to each idea before including it:\n"
        "  1. Is the hook a question or shock statement (NOT a topic title)? → If not, rewrite.\n"
        "  2. Would a mid-scroll viewer feel a psychological NEED to watch? → If not, rewrite.\n"
        "  3. Does it genuinely fit the domain perspective above? → If not, rewrite.\n\n"
        f'Return JSON exactly: {{"ideas": [{{...}}]}}'
    )


def _standard_user_prompt(n: int, extra: str = "") -> str:
    return (
        f"Generate exactly {n} short video ideas following the Human Attention Engine framework.\n\n"
        f"{_date_context()}\n\n"
        f"{extra}\n\n"
        "HARD REQUIREMENTS:\n"
        f"  — Return exactly {n} ideas, numbered internally for your own verification.\n"
        "  — Every hook is a question (ending in ?) or a shock statement. Never a topic.\n"
        "  — Every idea triggers at least 2 mechanisms. Aim for 3.\n"
        "  — No two ideas share the same primary mechanism combination.\n"
        "  — Cover at least 4 different subject territories across the batch.\n"
        "  — All facts must be real and verifiable.\n\n"
        "FINAL SELF-CHECK — apply this to each idea before including it:\n"
        "  1. Is the hook a question or shock statement (NOT a topic title)? → If not, rewrite.\n"
        "  2. Would a mid-scroll viewer feel a psychological NEED to watch? → If not, rewrite.\n"
        "  3. Does it trigger at least 2 mechanisms genuinely? → If not, rewrite.\n\n"
        f'Return JSON exactly: {{"ideas": [{{...}}]}}'
    )


# ── LLM operations ────────────────────────────────────────────────────────────

async def generate(n: int, s: dict, key: str, diverse: bool = False, progress=None, sink: list | None = None, sigs: list | None = None) -> list[dict]:
    """Generate n ideas. diverse=True splits across domain lenses for variety. Each idea is saved as soon as it is written; `sink` gets it at once and `progress(done, total, label)` says where the run is."""
    from . import discover
    sink = sink if sink is not None else []
    sigs = sigs or []
    avoid = avoid_text()
    extra = "\n\n".join(x for x in (discover.block(sigs), feedback_extra(n, diverse), ("ALREADY COVERED OR REJECTED (do not make an idea about the same subject, event or question as any of these):\n" + avoid) if avoid else "") if x)
    if not diverse:
        backend = llm_mod.ChatBackend(s, key)
        caller  = llm_mod.JsonCaller(backend, s)
        caller.last_attempt = True
        if progress:
            progress(0, 1, f"writing {n} ideas")
        result = await caller.call(_generate_system(), _standard_user_prompt(n, extra), _IdeasBatch)
        specs  = (result.value.ideas or [])[:n]
        for sp in specs:
            sink.append(add(sp.title, sp.hook, sp.mechanisms, sp.premise, sp.why_works, discover.pick(sigs, sp.sources), sp.territory))
        _plan_sources(sink)
        return list(sink)

    # Diverse mode: distribute n across lenses, one sequential call per lens
    lens_count = min(len(_LENSES), n)
    # distribute n as evenly as possible — first (n % lens_count) lenses get one extra
    counts = [n // lens_count + (1 if i < n % lens_count else 0) for i in range(lens_count)]

    for k, (lens, count) in enumerate(zip(_LENSES[:lens_count], counts)):
        if progress:
            progress(k, lens_count, f"lens {k + 1} of {lens_count}: {lens['perspective']}")
        backend = llm_mod.ChatBackend(s, key)
        caller  = llm_mod.JsonCaller(backend, s)
        caller.last_attempt = True
        try:
            result = await caller.call(_generate_system(), _lens_user_prompt(count, lens, extra), _IdeasBatch)
            specs  = (result.value.ideas or [])[:count]
            for sp in specs:
                sink.append(add(sp.title, sp.hook, sp.mechanisms, sp.premise, sp.why_works, discover.pick(sigs, sp.sources), sp.territory))
        except Exception as e:
            print(f"[ideas] lens '{lens['perspective']}' failed: {e}", flush=True)
    if progress:
        progress(lens_count, lens_count, "ideas written")
    _plan_sources(sink)
    return list(sink)


def _rating_anchors() -> str:
    """Past ideas with their score and their real grade on the channel (only while an approved Playbook is in use)."""
    try:
        from feedback import playbook
        return playbook.rating_anchors()
    except Exception as e:  # noqa: BLE001
        print(f"[feedback] anchors failed: {e}", flush=True)
        return ""


async def rate(idea_ids: list[str], s: dict, key: str) -> list[dict]:
    """Score ideas and rank by engagement_score. Empty idea_ids = all ideas."""
    ideas = listing() if not idea_ids else [get(i) for i in idea_ids]
    if not ideas:
        return []

    backend = llm_mod.ChatBackend(s, key)
    caller  = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True

    ideas_json = db.jdump([
        {"id": i["id"], "title": i["title"], "hook": i["hook"],
         "mechanisms": i["mechanisms"], "premise": i["premise"], "why_works": i["why_works"]}
        for i in ideas
    ])

    user = (
        f"Score these {len(ideas)} short video ideas against the YouTube Shorts engagement framework.\n\n"
        f"IDEAS:\n{ideas_json}\n\n"
        f"{_rating_anchors()}"
        "CALIBRATION INSTRUCTIONS:\n"
        "  — Score each idea independently first.\n"
        "  — Then review all scores comparatively and adjust so the distribution reflects\n"
        "    genuine relative quality. The best idea should score meaningfully higher than the worst.\n"
        "  — Do NOT cluster all scores at 7-8. Use the full range.\n"
        "  — A mediocre hook that breaks the BAD/GOOD test should score 3-5 on hook_strength.\n\n"
        f'Return JSON exactly: {{"scores": [{{...}}]}}'
    )

    result = await caller.call(_RATE_SYSTEM, user, _ScoreBatch)

    for sc in result.value.scores or []:
        breakdown = {
            "hook_strength":          sc.hook_strength,
            "mechanism_count":        sc.mechanism_count,
            "emotional_intensity":    sc.emotional_intensity,
            "completion_rate":        sc.completion_rate,
            "novelty":                sc.novelty,
            "progressive_revelation": sc.progressive_revelation,
            "shareability":           sc.shareability,
            "reasoning":              sc.reasoning,
            "verdict":                sc.verdict,
        }
        try:
            save_score(sc.id, sc.engagement_score, breakdown)
        except ValueError:
            pass  # stale id

    all_ideas = listing() if not idea_ids else [get(i) for i in idea_ids]
    return sorted(all_ideas, key=lambda x: x["engagement_score"], reverse=True)


def _styles_text(styles: list[str]) -> str:
    from . import looks
    pres = looks.presets()
    return ("\nALLOWED PICTURE STYLES: the visual_direction MUST name exactly one of these style ids and may use no other: "
            + "; ".join(f"{x} ({pres[x]['label']})" for x in styles if x in pres) + ".\n")


def direction_choice(direction: str, styles: list[str]) -> tuple[str, str]:
    """The visual direction names one of the allowed styles, and how that style was chosen (`idea`, `exploit`, `explore`, `rotation`). If the model named none (or one that is not allowed), the style the queue would pick comes first, in bright light."""
    d = (direction or "").strip()
    if not styles or any(re.search(rf"\b{re.escape(x)}\b", d.lower()) for x in styles):
        return d, "idea"
    style, src = style_choice(styles, "")
    return f"{style} - bright natural light, clean palette. {d}".strip(), src


def direction_with_style(direction: str, styles: list[str]) -> str:
    return direction_choice(direction, styles)[0]


async def condition(idea_id: str, s: dict, key: str, styles: list[str] | None = None) -> dict:
    """Expand an approved idea into a full production brief."""
    idea = get(idea_id)
    if idea["status"] not in ("approved", "conditioned"):
        raise ValueError("idea must be approved before conditioning")

    backend = llm_mod.ChatBackend(s, key)
    caller  = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True
    # The picture style is chosen here, in code (the Playbook's bandit, else the least used ticked style), never by the model: left to choose, it named the same style (filmic) every time.
    pick = style_choice([x for x in (styles or []) if x], "")[0] if styles else ""
    one_style = [pick] if pick else []

    user = (
        f"Sharpen this approved short video idea into a concept for the writers' room.\n\n"
        f"IDEA TITLE: {idea['title']}\n"
        f"HOOK: {idea['hook']}\n"
        f"MECHANISMS TRIGGERED: {', '.join(idea['mechanisms'])}\n"
        f"PREMISE: {idea['premise']}\n"
        f"WHY IT WORKS (analyst notes): {idea['why_works']}\n"
        + (
            f"\nENGAGEMENT SCORE: {idea['engagement_score']:.1f}/10\n"
            f"ANALYST VERDICT: {idea['score_breakdown'].get('verdict', '')}\n"
            f"ANALYST REASONING: {idea['score_breakdown'].get('reasoning', '')}\n"
            if idea.get("engagement_score") else ""
        )
        + (_styles_text(one_style) if one_style else "") +
        "\nRemember: SHARPEN, never sanitise. The concept must be MORE psychologically "
        "powerful than the input idea. Do not plan beats, timings, emotions or lines.\n\n"
        f'Return JSON exactly: {{"conditioning": {{...}}}}'
    )

    result = await caller.call(_CONDITION_SYSTEM, user, _ConditionResult)
    c = result.value.conditioning
    direction, style_src = direction_choice(c.visual_direction, one_style)
    brief = {
        "refined_hook":      c.refined_hook,
        "key_facts":         c.key_facts,
        "visual_direction":  direction,
        "suggested_tone":    c.suggested_tone,
        "style_src":         style_src,
        "style":             pick,
    }
    out = save_conditioning(idea_id, brief)
    if pick:                                                                  # counted by the rotation from now on, so the next brief gets another style
        db.ex("UPDATE short_ideas SET style=? WHERE id=?", (pick, idea_id))
        out = get(idea_id)
    return out
