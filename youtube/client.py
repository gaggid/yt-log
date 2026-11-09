"""The read-only YouTube calls: the channel and its uploads (Data API v3) and the daily numbers of a video (Analytics API v2)."""
import re
from datetime import datetime, timezone

from . import oauth
from .oauth import YTError

DATA = "https://www.googleapis.com/youtube/v3"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
METRICS = ("views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "likes", "comments", "shares", "subscribersGained")


async def _get(url: str, params: dict) -> dict:
    tok = await oauth.access_token()
    async with oauth.http() as c:
        r = await c.get(url, params=params, headers={"Authorization": f"Bearer {tok}"})
    if r.status_code == 401:
        raise oauth.YTAuthError("YouTube refused the saved sign-in. Connect again.")
    if r.status_code >= 400:
        raise YTError(f"YouTube answered {r.status_code}: {oauth._problem(r)}")
    return r.json()


def parse_duration(iso: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def parse_time(iso: str) -> float:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return 0.0


async def my_channel() -> dict:
    j = await _get(f"{DATA}/channels", {"part": "snippet,contentDetails", "mine": "true"})
    items = j.get("items") or []
    if not items:
        raise YTError("This Google account has no YouTube channel")
    c = items[0]
    return {"id": c["id"], "title": c.get("snippet", {}).get("title", ""), "uploads": c.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")}


async def upload_ids(playlist_id: str, limit: int = 200) -> list[str]:
    ids: list[str] = []
    token = ""
    while len(ids) < limit:
        j = await _get(f"{DATA}/playlistItems", {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50, **({"pageToken": token} if token else {})})
        ids += [i["contentDetails"]["videoId"] for i in j.get("items", []) if i.get("contentDetails", {}).get("videoId")]
        token = j.get("nextPageToken", "")
        if not token:
            break
    return ids[:limit]


async def videos(ids: list[str]) -> list[dict]:
    out: list[dict] = []
    for n in range(0, len(ids), 50):
        j = await _get(f"{DATA}/videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids[n:n + 50])})
        for v in j.get("items", []):
            st = v.get("statistics", {})
            out.append({"video_id": v["id"], "title": v.get("snippet", {}).get("title", ""), "published_at": parse_time(v.get("snippet", {}).get("publishedAt", "")),
                        "duration_s": parse_duration(v.get("contentDetails", {}).get("duration", "")), "views": int(st.get("viewCount", 0) or 0),
                        "likes": int(st.get("likeCount", 0) or 0), "comments": int(st.get("commentCount", 0) or 0)})
    return out


async def comments(video_id: str, limit: int = 30) -> list[dict]:
    """The most relevant public comments of a video (plain text)."""
    j = await _get(f"{DATA}/commentThreads", {"part": "snippet", "videoId": video_id, "maxResults": min(limit, 100), "order": "relevance", "textFormat": "plainText"})
    out = []
    for it in j.get("items", []):
        sn = it.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        if sn.get("textDisplay") or sn.get("textOriginal"):
            out.append({"comment_id": it["id"], "text": (sn.get("textOriginal") or sn.get("textDisplay") or "")[:600], "likes": int(sn.get("likeCount", 0) or 0), "published_at": parse_time(sn.get("publishedAt", ""))})
    return out


async def daily(video_id: str, start: str, end: str) -> list[dict]:
    """One row per day from `start` to `end` (YYYY-MM-DD) for one video."""
    j = await _get(ANALYTICS, {"ids": "channel==MINE", "startDate": start, "endDate": end, "metrics": ",".join(METRICS), "dimensions": "day", "filters": f"video=={video_id}", "sort": "day"})
    names = [h["name"] for h in j.get("columnHeaders", [])]
    out = []
    for row in j.get("rows", []) or []:
        d = dict(zip(names, row))
        out.append({"day": d.get("day", ""), "views": int(d.get("views", 0) or 0), "minutes": float(d.get("estimatedMinutesWatched", 0) or 0), "avg_view_s": float(d.get("averageViewDuration", 0) or 0),
                    "avg_view_pct": float(d.get("averageViewPercentage", 0) or 0), "likes": int(d.get("likes", 0) or 0), "comments": int(d.get("comments", 0) or 0),
                    "shares": int(d.get("shares", 0) or 0), "subs": int(d.get("subscribersGained", 0) or 0)})
    return out
