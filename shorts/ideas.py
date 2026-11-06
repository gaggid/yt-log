"""Short Ideas parking lot — generate, rate, approve, condition, queue.

Flow: pending → approved → conditioned → queued (short created) | rejected
"""
import hashlib

from story import db, llm as llm_mod, settings as settings_mod
from story.schemas import M, Str

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
"""

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
    narrative_arc:     list[str] = []
    emotional_journey: list[str] = []
    key_facts:         list[str] = []
    visual_direction:  Str       = ""
    suggested_tone:    Str       = ""
    opening_line:      Str       = ""
    production_notes:  Str       = ""


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
      "why_works": "4-6 sentences. Analyse specifically which attention triggers fire and WHY this particular subject activates them psychologically. Be analytical, not promotional."
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
You are a senior short-video producer preparing an approved idea for immediate production.
Your job is to take an approved idea and expand it into a complete, unambiguous production brief.

CRITICAL RULE — SHARPEN, NEVER SANITISE:
You are making the idea MORE psychologically powerful, not softening it into a topic description.
The final brief must be harder-hitting than the input. If you flatten it, you have failed.

═══════════════════════════════════════════════════════════════════
PRODUCTION BRIEF REQUIREMENTS
═══════════════════════════════════════════════════════════════════

1. REFINED HOOK (required)
   Rewrite the original hook to be even more psychologically precise and visceral.
   Rules:
   - Maximum 15 words.
   - Must work as the first spoken sentence OR the on-screen title.
   - Must trigger the stated attention mechanisms harder than the original.
   - Must be a question (?) or a shock statement. Never a topic label.
   - Self-test: would a viewer who was mid-scroll stop dead?

2. NARRATIVE ARC — the 30-second journey (exactly 5 items)
   Cover these time windows: 0-5s, 5-10s, 10-15s, 15-25s, 25-30s.
   Each item is ONE specific sentence: what the narrator says AND what appears on screen.
   Format: "0-5s: [exact description]"
   Rules:
   - Every beat must change the viewer's understanding of what they are watching.
   - The structure must escalate. Each beat must be more surprising than the last.
   - The STRONGEST reveal goes at 25-30s. Never earlier.
   - No vague descriptions. Specific > general. "12,000 Indian soldiers" not "many soldiers."

3. EMOTIONAL JOURNEY (exactly 5 items matching arc timing)
   Format: "0-5s: [primary emotion]"
   Rules:
   - Emotions must escalate. Never start at the peak.
   - Allowed emotions: curiosity, unease, anticipation, disbelief, fear, awe, pride,
     righteous anger, surprise, cognitive dissonance, admiration, shock.

4. KEY FACTS (3-5 items)
   Specific, verifiable facts that anchor the narrative.
   These are the production team's research targets.
   Rules:
   - Each fact must be specific enough to verify independently.
   - Bad: "India has a large military." Good: "India's mountain warfare corps operates at Siachen at 22,000 feet — the highest active battlefield on Earth."
   - No invented statistics. No approximated numbers presented as exact.

5. VISUAL DIRECTION
   One clear sentence for the image model and director.
   Include: style (realism/filmic/documentary/animated/concept-art), colour palette, lighting mood.
   Example: "Cold, desaturated realism — steel-grey palette, harsh overhead light, documentary handheld feel."

6. SUGGESTED TONE
   Pick exactly ONE from this list: storyteller, soothing, documentary, bigbro, explorer, thriller, roaster
   Follow with one sentence explaining why this tone amplifies the specific emotional triggers of this idea.

7. OPENING LINE
   The EXACT first spoken sentence of the narration in Hinglish (mixed Hindi-English).
   Must match the refined hook perfectly.
   Maximum 12 words.
   Must feel urgent. Must be a question or a shock statement.

8. PRODUCTION NOTES
   Critical notes for the director: pacing warnings, visual challenges, what could go wrong,
   suggested shot types (close-up / satellite view / infographic / archival footage feel),
   any specific transition moments to design around.

OUTPUT FORMAT — return valid JSON only, no explanation outside the JSON:
{
  "conditioning": {
    "refined_hook": "...",
    "narrative_arc": ["0-5s: ...", "5-10s: ...", "10-15s: ...", "15-25s: ...", "25-30s: ..."],
    "emotional_journey": ["0-5s: ...", "5-10s: ...", "10-15s: ...", "15-25s: ...", "25-30s: ..."],
    "key_facts": ["...", "...", "..."],
    "visual_direction": "...",
    "suggested_tone": "...",
    "opening_line": "...",
    "production_notes": "..."
  }
}"""


# ── CRUD ──────────────────────────────────────────────────────────────────────

def ensure() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def _load(r: dict | None) -> dict | None:
    if r is None:
        return None
    r = dict(r)
    r["mechanisms"]     = db.jload(r.get("mechanisms"), [])
    r["score_breakdown"] = db.jload(r.get("score_breakdown"), {})
    r["conditioning"]   = db.jload(r.get("conditioning"), {})
    return r


def add(title: str, hook: str, mechanisms: list, premise: str, why_works: str) -> dict:
    ensure()
    iid = f"idea-{hashlib.sha1(f'{hook}{db.now()}'.encode()).hexdigest()[:8]}"
    db.ex(
        "INSERT INTO short_ideas(id,title,hook,mechanisms,premise,why_works,status,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (iid, title, hook, db.jdump(mechanisms), premise, why_works, "pending", db.now(), db.now()),
    )
    return get(iid)


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
    return get(idea_id)


def save_score(idea_id: str, score: float, breakdown: dict) -> dict:
    ensure()
    db.ex("UPDATE short_ideas SET engagement_score=?, score_breakdown=?, updated_at=? WHERE id=?",
          (score, db.jdump(breakdown), db.now(), idea_id))
    return get(idea_id)


def save_conditioning(idea_id: str, conditioning: dict) -> dict:
    ensure()
    db.ex("UPDATE short_ideas SET conditioning=?, status=?, updated_at=? WHERE id=?",
          (db.jdump(conditioning), "conditioned", db.now(), idea_id))
    return get(idea_id)


def delete_idea(idea_id: str) -> None:
    ensure()
    db.ex("DELETE FROM short_ideas WHERE id=?", (idea_id,))


# ── LLM operations ────────────────────────────────────────────────────────────

async def generate(n: int, s: dict, key: str) -> list[dict]:
    """Generate n ideas using the Human Attention Engine framework."""
    backend = llm_mod.ChatBackend(s, key)
    caller  = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True

    user = (
        f"Generate exactly {n} short video ideas following the Human Attention Engine framework.\n\n"
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

    result = await caller.call(_GENERATE_SYSTEM, user, _IdeasBatch)
    specs  = (result.value.ideas or [])[:n]
    return [add(sp.title, sp.hook, sp.mechanisms, sp.premise, sp.why_works) for sp in specs]


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


async def condition(idea_id: str, s: dict, key: str) -> dict:
    """Expand an approved idea into a full production brief."""
    idea = get(idea_id)
    if idea["status"] not in ("approved", "conditioned"):
        raise ValueError("idea must be approved before conditioning")

    backend = llm_mod.ChatBackend(s, key)
    caller  = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True

    user = (
        f"Expand this approved short video idea into a full production brief.\n\n"
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
        ) +
        "\nRemember: SHARPEN, never sanitise. The brief must be MORE psychologically "
        "powerful than the input idea.\n\n"
        f'Return JSON exactly: {{"conditioning": {{...}}}}'
    )

    result = await caller.call(_CONDITION_SYSTEM, user, _ConditionResult)
    c = result.value.conditioning
    brief = {
        "refined_hook":      c.refined_hook,
        "narrative_arc":     c.narrative_arc,
        "emotional_journey": c.emotional_journey,
        "key_facts":         c.key_facts,
        "visual_direction":  c.visual_direction,
        "suggested_tone":    c.suggested_tone,
        "opening_line":      c.opening_line,
        "production_notes":  c.production_notes,
    }
    return save_conditioning(idea_id, brief)
