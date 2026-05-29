import re

_ARTIST_NOISE_PATTERNS = [
    r"\bofficial\b",
    r"\bvideo\b",
    r"\blyrics?\b",
    r"\blive\b",
    r"\bremix\b",
    r"\baudio\b",
    r"\btopic\b",
    r"\bvevo\b",
    r"\brecords?\b",
]


def _normalize_artist_token(value: str) -> str:
    cleaned = (value or "").strip()
    cleaned = re.sub(r"[\(\[].*?[\)\]]", " ", cleaned)
    cleaned = re.sub("|".join(_ARTIST_NOISE_PATTERNS), " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_")
    return cleaned

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

def mb_artist_candidates(artist_guess: str) -> list[str]:
    raw = (artist_guess or "").strip()
    if not raw:
        return []
    vals = [raw]
    # Split multi-artist forms and keep likely primary candidates first.
    for sep in [" x ", " & ", ",", " / ", " and "]:
        if sep in raw.lower():
            parts = [p.strip() for p in re.split(re.escape(sep), raw, flags=re.IGNORECASE) if p.strip()]
            vals.extend(parts)
            break
    norm = []
    seen = set()
    for v in vals:
        cleaned = _normalize_artist_token(v)
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            norm.append(cleaned)
    return norm[:5]
