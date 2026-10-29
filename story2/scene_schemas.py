"""Model-output schemas and constants for the storyboard (batch B). Lenient about harmless variations."""
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, field_validator

from story import schemas as s1

from . import maya

Str, StrList = s1.Str, s1.StrList

VISUAL_TYPES = (
    "reconstruction", "establishing", "character", "metaphor", "object_process", "montage", "map_timeline", "data_chart",
    "document_archival", "screen_interface", "diagram", "comparison", "text_led", "minimalist", "atmospheric", "transition")
_VT_ALIAS = {
    "historical_reconstruction": "reconstruction", "documentary": "reconstruction", "documentary_reconstruction": "reconstruction",
    "environment": "establishing", "establishing_shot": "establishing", "place": "establishing", "close_up": "character",
    "reaction": "character", "portrait": "character", "symbolic": "metaphor", "visual_metaphor": "metaphor", "object": "object_process",
    "process": "object_process", "demonstration": "object_process", "documentary_montage": "montage", "map": "map_timeline",
    "timeline": "map_timeline", "chart": "data_chart", "graph": "data_chart", "financial_chart": "data_chart", "data": "data_chart",
    "data_visualisation": "data_chart", "data_visualization": "data_chart", "document": "document_archival", "archival": "document_archival",
    "screen": "screen_interface", "interface": "screen_interface", "ui": "screen_interface", "infographic": "diagram",
    "before_after": "comparison", "text": "text_led", "negative_space": "minimalist", "mood": "atmospheric", "bridge": "transition"}
# these cannot be trusted to an image model: the content must be a verified asset or built deterministically later
NEEDS_ASSET = {"data_chart", "document_archival", "screen_interface", "map_timeline", "diagram"}
ASSET_KINDS = ("person", "place", "prop", "style", "narrator")
FICTIONALISATION = ("generic_reconstruction", "source_supported", "real_person_no_likeness", "fictional")
ASPECTS = {"16:9": (1344, 768), "9:16": (768, 1344)}


def norm_visual_type(v):
    v = s1._str(v).lower().replace(" ", "_").replace("-", "_").replace("/", "_")
    v = _VT_ALIAS.get(v, v)
    return v if v in VISUAL_TYPES else "atmospheric"


def _kind(v):
    v = s1._str(v).lower()
    v = {"character": "person", "people": "person", "location": "place", "setting": "place", "object": "prop", "look": "style"}.get(v, v)
    return v if v in ASSET_KINDS else "prop"


def _fict(v):
    v = s1._str(v).lower().replace(" ", "_").replace("-", "_")
    return v if v in FICTIONALISATION else "generic_reconstruction"


def _range(v):
    if isinstance(v, (int, float)):
        return [int(v), int(v)]
    if isinstance(v, str):
        v = [int(x) for x in __import__("re").findall(r"\d+", v)]
    v = [int(x) for x in (v or []) if str(x).lstrip("-").isdigit()]
    if not v:
        return []
    return [min(v), max(v)] if len(v) > 1 else [v[0], v[0]]


def _shot(v):
    """The director's shot number, however the model wrote it (3, "3", "shot 3", [3, 4]); 0 when there is none."""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else 0
    m = __import__("re").search(r"\d+", str(v if v is not None else ""))
    return int(m.group()) if m else 0


class M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AssetOut(M):
    name: Str
    kind: Annotated[str, BeforeValidator(_kind)] = "prop"
    description: Str = ""                           # approved visual attributes, only what is supported or deliberately fictional
    appearance: dict[str, Str] = {}                  # one concrete value per slot (story2/describe.py); the description is composed from it
    fixed: StrList = []                              # must stay the same in every scene
    flexible: StrList = []                           # may change between scenes
    period: Str = ""
    fictionalisation: Annotated[str, BeforeValidator(_fict)] = "generic_reconstruction"
    evidence_note: Str = ""                          # what in the story supports it, in our words
    literal: bool = True                             # false when it is an idea, a figure of speech, a chart feature or a group rather than one thing in the scene
    life_stages: list[dict] = []                     # a person shown at more than one age: [{from_year, to_year, age, look_changes}]


class RegistryOut(M):
    assets: list[AssetOut]

    @field_validator("assets")
    @classmethod
    def _a(cls, v):
        if not v:
            raise ValueError("the registry needs at least a style asset")
        return v


class Compose(M):
    position: Str = ""
    left: Str = ""
    centre: Str = ""
    right: Str = ""
    camera_angle: Str = ""
    distance: Str = ""
    perspective: Str = ""
    framing: Str = ""


class OnScreen(M):
    text: Str
    placement: Str = ""


class SceneOut(M):
    sentences: Annotated[list[int], BeforeValidator(_range)] = []
    idea: Str = ""                                   # what the narration MEANS here, in plain words (the thing to carry, not the words to draw)
    translation: Str = ""                            # the concrete moment in the story's world (who, where, doing what) that carries that idea
    event: Str = ""                                  # the visual event (story2/events.py) this scene shows; empty for scenes planned without events
    shot: Annotated[int, BeforeValidator(_shot)] = 0                                    # the number of the director's shot this scene follows (0: none)
    purpose: Str
    new_information: Str = ""                        # what the viewer learns, notices or feels that the previous visual did not give
    takeaway: Str = ""
    emotional_effect: Str = ""
    voice_tag: Annotated[str, BeforeValidator(maya.norm_tag)] = ""   # how the narrator should sound over this scene (Maya tag, or neutral)
    visual_type: Annotated[str, BeforeValidator(norm_visual_type)] = "atmospheric"
    subject: Str
    action: Str = ""
    location: Str = ""
    period: Str = ""
    props: StrList = []
    composition: Compose = Compose()
    lighting: Str = ""
    palette: Str = ""
    atmosphere: Str = ""
    style: Str = ""
    foreground: Str = ""
    middle: Str = ""
    background: Str = ""
    motion_intent: Str = ""
    text_on_screen: list[OnScreen] = []
    assets: StrList = []                             # names of registry assets used
    use_ref_assets: StrList = []                     # subset whose reference images should be sent; empty = use all (omit place/prop refs for atmospheric/abstract scenes)
    fixed_by_facts: StrList = []                     # visual details that come from the story's facts
    creative_choices: StrList = []                   # details that are our creative decisions
    exclusions: StrList = []
    needs_asset: Str = ""                            # for charts, documents, screens, maps: what verified asset is required
    fallback: Str = ""
    pov: dict = {}                                   # set by the director's plan, never by the model: {"through": "a phone screen", "of": "who looks"}
    motion_clip: bool = False                        # user opted this scene into Wan 2.2 animation

    @field_validator("purpose", "subject")
    @classmethod
    def _need(cls, v):
        if not v:
            raise ValueError("purpose and subject are required")
        return v


class ScenesOut(M):
    scenes: list[SceneOut]

    @field_validator("scenes")
    @classmethod
    def _s(cls, v):
        if not v:
            raise ValueError("no scenes returned")
        return v
