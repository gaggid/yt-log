"""Which pipeline made a plan's work. A plan stores `settings.pipeline` when it is created and `settings.<stage>_pipeline` when a stage runs; a plan with none of them
was made before pipelines were numbered and counts as "q1". `PIPELINE` is raised only when a change makes older work wrong for the new rules (see
docs/TASKS_quality_overhaul.md), so the plan screen can say "made with an older pipeline" and lead through redoing the stage, as it does for the visual style."""

PIPELINE = "q2"                  # q2: Material Pack, three-pass narration, visual events, one-paragraph picture prompts (docs/TASKS_quality_overhaul.md)
STAGES = ("narration", "storyboard")


def of(plan_settings: dict | None, stage: str = "") -> str:
    st = plan_settings or {}
    return str((st.get(f"{stage}_pipeline") if stage else None) or st.get("pipeline") or "q1")


def at_least(plan_settings: dict | None, level: str, stage: str = "") -> bool:
    """Was the work (of one stage, or of the plan) made with this pipeline or a newer one? Levels compare as q1 < q2 < q3."""
    return of(plan_settings, stage) >= level


def stale(plan_settings: dict | None, stage: str = "") -> bool:
    return of(plan_settings, stage) < PIPELINE


def stamp(plan_settings: dict | None, stage: str = "") -> dict:
    """The settings dict with the current pipeline written for the plan or one stage."""
    return {**(plan_settings or {}), (f"{stage}_pipeline" if stage else "pipeline"): PIPELINE}
