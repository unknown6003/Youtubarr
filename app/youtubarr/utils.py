import os
import re
from ytmusicapi import YTMusic, OAuthCredentials
from django.conf import settings

def guess_artist_from_title(title: str, channel_title: str) -> str:
    """
    Heuristics:
    - 'Artist - Song' => take left half
    - Channel like 'Foo - Topic' => use 'Foo'
    - Otherwise: empty string (we'll skip for MB search)
    """
    if " - " in title:
        left = title.split(" - ", 1)[0].strip()
        left = re.split(r"\s*(feat\.?|ft\.?|featuring)\s+", left, flags=re.IGNORECASE)[0].strip()
        left = re.sub(r"[\(\[].*?[\)\]]", "", left).strip()
        # avoid generic prefixes like "Official Video"
        if len(left) >= 2:
            return left
    if " - Topic" in channel_title:
        return channel_title.replace(" - Topic", "").strip()
    if channel_title and (" - " in channel_title or "topic" in channel_title.lower() or "vevo" in channel_title.lower()):
        cleaned = re.split(r"\s*(official|records|vevo)\b", channel_title, flags=re.IGNORECASE)[0].strip()
        cleaned = cleaned.replace("- Topic", "").strip()
        if cleaned and len(cleaned) >= 2:
            return cleaned
    return ""

def get_ytmusic():
    """Return a YTMusic instance. Requires oauth.json."""
    data_dir = "/data"
    json_path = os.path.join(data_dir, "oauth.json")

    if not os.path.exists(json_path):
        raise RuntimeError("No oauth.json found in /data")

    return YTMusic(json_path)

def fetch_liked_music():
    ytmusic = get_ytmusic()
    playlist = ytmusic.get_playlist("LM")
    items = []
    for track in playlist["tracks"]:
        vid = track.get("videoId")
        if not vid:
            continue
        items.append({
            "video_id": vid,
            "title": track.get("title", ""),
            "artist": (track.get("artists") or [{}])[0].get("name", ""),
        })
    return items
