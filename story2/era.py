"""Right objects, right look for each time (docs/TASKS_quality_overhaul.md task 3.13; audit 14.3 and 14.5). A story that spans decades must not show a smartphone in 1991, and the
past should look like the past: the table below lists what did not exist yet in India (so a scene that shows it is sent back), the `look` words the picture prompt adds for the
time, a mild colour grade the video applies to the clip, and the year label shown for a moment when the film jumps in time.

The dates are for India and are deliberately cautious: an object is forbidden only before it was certainly absent from ordinary life; an object that was rare is `suspect`
(a warning, not an error)."""
import re

NOW = 2026

# (regex, first year it can be seen in ordinary Indian life, what it is). A scene set before that year may not show it.
FORBIDDEN = [
    (r"smart ?phone|iphone|android|touch ?screen phone|phone with a touch ?screen", 2010, "a smartphone"),
    (r"mobile phone|cell ?phone|cellular phone|handheld phone", 1996, "a mobile phone"),
    (r"whatsapp|upi\b|qr code|paytm|phonepe|google pay|online payment app", 2015, "a payment or messaging app"),
    (r"e-?rickshaw|electric rickshaw|battery rickshaw", 2010, "an e-rickshaw"),
    (r"led (?:bulb|light|lamp|tv|screen)|flat[- ]screen|lcd (?:tv|screen|monitor)", 2007, "an LED or flat screen"),
    (r"smart ?watch|fitness band|earbuds|airpods|bluetooth headset", 2014, "a smartwatch or earbuds"),
    (r"laptop|notebook computer", 1996, "a laptop"),
    (r"selfie", 2010, "a selfie"),
    (r"drone", 2012, "a drone"),
    (r"digital camera|dslr", 1999, "a digital camera"),
    (r"cctv|security camera|surveillance camera", 1992, "a CCTV camera"),
    (r"ride[- ]?hailing|ola cab|uber|food delivery app|zomato|swiggy", 2012, "an app-based cab or delivery"),
    (r"metro train|metro station|metro rail", 2002, "a metro train"),
    (r"atm machine|\batm\b|cash machine", 1993, "an ATM"),
    (r"flyover", 1960, "a flyover"),
]
# before this year the object was possible but rare in an ordinary small-town scene: a warning, not an error
SUSPECT = [
    (r"cctv|security camera", 2005, "a CCTV camera in an ordinary lane"),
    (r"smart ?phone|touch ?screen", 2014, "a smartphone for an ordinary person"),
    (r"mobile phone|cell ?phone", 2003, "a mobile phone for an ordinary person"),
    (r"laptop", 2005, "a laptop at an ordinary home"),
    (r"air conditioner|\bac unit\b", 1995, "an air conditioner at an ordinary home"),
]
# objects that suit a time and make it readable; offered to the registry and to inserts as props
PERIOD_PROPS = {
    (1950, 1979): "black rotary telephone, kerosene lamp, cloth ration bag, bicycle, radio set, hand-cranked fan, Ambassador car",
    (1980, 1994): "black rotary phone, STD booth with a yellow sign, ceiling fan, Ambassador and Fiat cars, tube light, cassette player, Doordarshan television",
    (1995, 2004): "keypad mobile phone with a small grey screen, STD-PCO booth, CRT television, Maruti 800, cyber cafe with a bulky monitor",
    (2005, 2013): "keypad and early touch phones, flat TV, motorbikes, DTH dish on a roof, internet cafe, ATM kiosk",
    (2014, NOW): "smartphones with cracked screens, UPI QR code at a shop, e-rickshaws, CCTV domes, LED signboards, delivery bikes",
}
_YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


def year_of(text: str) -> int | None:
    """The year named in a period phrase ("August 1991" gives 1991); "present day", "now" and "today" give the current year; nothing gives None."""
    m = _YEAR.search(text or "")
    if m:
        return int(m.group())
    return NOW if re.search(r"present|now\b|today|current|modern|recent", text or "", re.I) else None


def problems(text: str, year: int | None) -> list[str]:
    """What in the text could not exist in that year, one sentence each; an empty list for an unknown year."""
    if not year or year >= 9999:
        return []
    low = (text or "").lower()
    return [f"{what} appears in a scene set in {year}: it did not exist in ordinary life in India before {first}" for rx, first, what in FORBIDDEN if year < first and re.search(rx, low)]


def suspects(text: str, year: int | None) -> list[str]:
    if not year or year >= 9999:
        return []
    low = (text or "").lower()
    return [f"{what} in {year} is possible but rare: make sure the story says so" for rx, first, what in SUSPECT if year < first and re.search(rx, low) and not any(rx2 == rx for rx2, f2, _ in FORBIDDEN if year < f2)]


def conflicts_with_story(text: str, story_text: str, year: int | None) -> list[str]:
    """A smartphone in a scene while the story's own details say the person had a keypad phone (the case that was drawn wrong in the audit)."""
    low, story = (text or "").lower(), (story_text or "").lower()
    if re.search(r"smart ?phone|touch ?screen", low) and re.search(r"keypad phone|feature phone|basic phone|button phone", story):
        return ["a smartphone is drawn, but the story's details say a keypad phone"]
    return []


def props_for(year: int | None) -> str:
    y = NOW if not year or year >= 9999 else year
    for (a, b), words in PERIOD_PROPS.items():
        if a <= y <= b:
            return words
    return ""


def look(year: int | None) -> str:
    """Words for the picture prompt: how the time period looks as a picture."""
    if not year or year >= 9999:
        return ""
    if year < 1980:
        return "faded warm colour, low contrast and visible film grain, like an old photograph"
    if year < 2000:
        return "slightly faded warm colour with soft film grain, like a photograph from that decade"
    if year < 2015:
        return "natural colour with a light grain"
    return ""


def grade(year: int | None) -> str:
    """An ffmpeg filter (or empty) that gives a clip the colour of its time: warmer and grainier before 2000, nothing for the present."""
    if not year or year >= 9999:
        return ""
    if year < 1980:
        return "eq=saturation=0.78:contrast=0.94:gamma_r=1.06:gamma_b=0.92,noise=alls=9:allf=t"
    if year < 2000:
        return "eq=saturation=0.88:contrast=0.97:gamma_r=1.04:gamma_b=0.95,noise=alls=6:allf=t"
    if year < 2010:
        return "eq=saturation=0.95,noise=alls=3:allf=t"
    return ""


def jumps(years: list[int | None]) -> list[int]:
    """Indices where the film moves to a different year than the scene before (the year label is shown there). Scenes with no year take the year before them."""
    out, cur = [], None
    for i, y in enumerate(years):
        if y is None:
            continue
        y = NOW if y >= 9999 else y
        if cur is not None and y != cur:
            out.append(i)
        cur = y
    return out
