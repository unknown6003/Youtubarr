import os
import subprocess
import time
import json
from collections.abc import Mapping
import requests
from dateutil import parser as dateparser
from django.conf import settings
from django.db import transaction
from celery import shared_task
from celery import chain
from .models import AppSettings, Playlist, TrackItem, Artist, Snapshot, FallbackImportJob
from .utils import guess_artist_from_title, mb_artist_candidates
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)
YT_API_ITEMS = "https://www.googleapis.com/youtube/v3/playlistItems"
YT_API_PLAYLISTS = "https://www.googleapis.com/youtube/v3/playlists"
YT_API_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
MB_API = "https://musicbrainz.org/ws/2/artist/"
MB_HEADERS = {"User-Agent": settings.MB_USER_AGENT}
MB_TIMEOUT_SECONDS = max(5, int(getattr(settings, "MB_TIMEOUT_SECONDS", 45)))
MB_MAX_RETRIES = max(1, int(getattr(settings, "MB_MAX_RETRIES", 4)))
MB_REQUEST_DELAY_SECONDS = max(0.2, float(getattr(settings, "MB_REQUEST_DELAY_SECONDS", 1.05)))
MB_ARTIST_CHUNK_SIZE = max(1, int(getattr(settings, "MB_ARTIST_CHUNK_SIZE", 100)))

def _get_api_key():
    s = AppSettings.load()
    return s.youtube_api_key or settings.YOUTUBE_API_KEY


def _get_oauth_bundle() -> dict:
    raw = getattr(settings, "YOUTUBE_OAUTH_JSON", "") or ""
    parsed = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, Mapping):
                logger.warning("YOUTUBE_OAUTH_JSON must decode to an object; falling back to explicit OAuth env vars.")
                parsed = {}
        except json.JSONDecodeError:
            logger.warning("Invalid YOUTUBE_OAUTH_JSON; falling back to explicit OAuth env vars.")
    return {
        "access_token": (parsed.get("access_token") or getattr(settings, "YOUTUBE_OAUTH_ACCESS_TOKEN", "") or ""),
        "refresh_token": (parsed.get("refresh_token") or getattr(settings, "YOUTUBE_OAUTH_REFRESH_TOKEN", "") or ""),
        "client_id": (parsed.get("client_id") or getattr(settings, "YOUTUBE_OAUTH_CLIENT_ID", "") or ""),
        "client_secret": (parsed.get("client_secret") or getattr(settings, "YOUTUBE_OAUTH_CLIENT_SECRET", "") or ""),
    }


def _refresh_access_token(bundle: dict) -> str:
    if not bundle["refresh_token"] or not bundle["client_id"] or not bundle["client_secret"]:
        return ""
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": bundle["client_id"],
            "client_secret": bundle["client_secret"],
            "refresh_token": bundle["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        logger.warning("YouTube OAuth token refresh failed: status=%s body=%s", resp.status_code, resp.text[:300])
        return ""
    token = (resp.json() or {}).get("access_token", "")
    return token or ""


def _youtube_get(url: str, params: dict):
    oauth = _get_oauth_bundle()
    if oauth["access_token"]:
        headers = {"Authorization": f"Bearer {oauth['access_token']}"}
        r = requests.get(url, params=params, headers=headers, timeout=30)
        if r.status_code in (401, 403):
            refreshed = _refresh_access_token(oauth)
            if refreshed:
                headers = {"Authorization": f"Bearer {refreshed}"}
                r = requests.get(url, params=params, headers=headers, timeout=30)
        return r

    api_key = _get_api_key()
    if not api_key:
        return None
    key_params = dict(params)
    key_params["key"] = api_key
    return requests.get(url, params=key_params, timeout=30)

def fetch_playlist_items(playlist: Playlist):
    if playlist.playlist_id == "LM":
        items = []
        params = {
            "part": "snippet,contentDetails",
            "myRating": "like",
            "maxResults": min(50, settings.YOUTUBE_QUOTA_SAFE_PAGE_SIZE),
        }
        while True:
            r = _youtube_get(YT_API_VIDEOS, params)
            if r is None:
                raise RuntimeError("No OAuth/API key available for LM fetch")
            if r.status_code != 200:
                raise RuntimeError(f"LM fetch failed: status={r.status_code} body={r.text[:300]}")
            data = r.json() or {}
            for entry in data.get("items", []):
                sn = entry.get("snippet", {})
                vd = entry.get("id")
                if not vd:
                    continue
                title = sn.get("title", "")
                channel = sn.get("channelTitle", "")
                items.append(
                    {
                        "video_id": vd,
                        "title": title,
                        "artist": guess_artist_from_title(title, channel),
                    }
                )
            token = data.get("nextPageToken")
            if not token:
                break
            params["pageToken"] = token
        count = 0
        for it in items:
            with transaction.atomic():
                ti, created = TrackItem.objects.get_or_create(
                    playlist=playlist,
                    video_id=it["video_id"],
                    defaults=dict(
                        title=it["title"],
                        artist_name_guess=it["artist"],
                        channel_title="YouTube Music",
                        position=0,  # LM doesn’t have stable positions
                        published_at=None,
                    ),
                )
                if not created:
                    ti.title = it["title"]
                    ti.artist_name_guess = it["artist"]
                    ti.save(update_fields=["title", "artist_name_guess"])
            count += 1
        playlist.title = "Liked Music"
        playlist.channel_title = "YouTube Music"
        playlist.last_synced = timezone.now()
        playlist.save(update_fields=["title", "channel_title", "last_synced"])
        return count
    if not _get_oauth_bundle()["access_token"] and not _get_api_key():
        return 0

    # --- Fetch playlist metadata ---
    meta_params = {
        "part": "snippet",
        "id": playlist.playlist_id,
    }
    rmeta = _youtube_get(YT_API_PLAYLISTS, meta_params)
    if rmeta is None:
        return 0
    if rmeta.status_code == 200:
        meta = rmeta.json()
        items = meta.get("items", [])
        if items:
            sn = items[0].get("snippet", {})
            playlist.title = sn.get("title", playlist.title)
            playlist.channel_title = sn.get("channelTitle", playlist.channel_title)
            playlist.last_synced = timezone.now()
            playlist.save(update_fields=["title", "channel_title", "last_synced"])
    else:
        logger.warning(
            "YouTube playlist metadata fetch failed for %s: status=%s body=%s",
            playlist.playlist_id,
            rmeta.status_code,
            rmeta.text[:300],
        )

    # --- Fetch playlist items ---
    params = {
        "part": "snippet,contentDetails",
        "playlistId": playlist.playlist_id,
        "maxResults": settings.YOUTUBE_QUOTA_SAFE_PAGE_SIZE,
    }
    count = 0
    url = YT_API_ITEMS
    while True:
        r = _youtube_get(url, params)
        if r is None:
            break
        if r.status_code != 200:
            logger.warning(
                "YouTube playlist items fetch failed for %s: status=%s body=%s",
                playlist.playlist_id,
                r.status_code,
                r.text[:300],
            )
            break
        data = r.json()

        for it in data.get("items", []):
            sn = it.get("snippet", {})
            vd = sn.get("resourceId", {}).get("videoId")
            title = sn.get("title", "")
            ch = sn.get("channelTitle", "")
            published = sn.get("publishedAt")
            artist_guess = guess_artist_from_title(title, ch)

            with transaction.atomic():
                ti, created = TrackItem.objects.get_or_create(
                    playlist=playlist,
                    video_id=vd,
                    defaults=dict(
                        title=title,
                        channel_title=ch,
                        position=sn.get("position", 0),
                        published_at=dateparser.parse(published) if published else None,
                        artist_name_guess=artist_guess,
                    )
                )

                if created:
                    # filled on creation, nothing more to do
                    pass
                else:
                    # only update "machine" fields that should always be current
                    ti.position = sn.get("position", ti.position)
                    ti.save(update_fields=["position"])

            count += 1

        token = data.get("nextPageToken")
        if not token:
            break
        params["pageToken"] = token
    return count


def search_mb_artist_mbid(name: str) -> str | None:
    for candidate in mb_artist_candidates(name):
        found = False
        params = {"query": f'artist:"{candidate}"', "fmt": "json"}
        for attempt in range(1, MB_MAX_RETRIES + 1):
            try:
                r = requests.get(MB_API, params=params, headers=MB_HEADERS, timeout=MB_TIMEOUT_SECONDS)
            except requests.RequestException as exc:
                logger.warning("MusicBrainz request failed for %r (attempt %d/%d): %s", candidate, attempt, MB_MAX_RETRIES, exc)
                if attempt < MB_MAX_RETRIES:
                    time.sleep(attempt * 1.5)
                continue

            if r.status_code == 200:
                js = r.json()
                arts = js.get("artists") or []
                if arts:
                    found = True
                    return arts[0]["id"]
                break

            if r.status_code in (429, 500, 502, 503, 504) and attempt < MB_MAX_RETRIES:
                logger.warning(
                    "MusicBrainz temporary status for %r: %s (attempt %d/%d)",
                    candidate,
                    r.status_code,
                    attempt,
                    MB_MAX_RETRIES,
                )
                time.sleep(attempt * 1.5)
                continue
            logger.warning("MusicBrainz lookup non-200 for %r: %s", candidate, r.status_code)
            break
        if not found:
            time.sleep(MB_REQUEST_DELAY_SECONDS)
    return None

@shared_task
def refresh_playlists():
    updated = 0
    for pl in Playlist.objects.filter(enabled=True):
        print(f"Fetching items for playlist {pl.playlist_id} ({pl.title})")
        try:
            updated += fetch_playlist_items(pl)
        except Exception as exc:
            logger.exception("Playlist sync failed for %s: %s", pl.playlist_id, exc)
    return updated

@shared_task
def resolve_missing_mbids():
    # Respect MB 1 rps
    names = list(
        TrackItem.objects
        .filter(blacklisted=False, artist__isnull=True)
        .exclude(artist_name_guess="")
        .values_list("artist_name_guess", flat=True)
        .distinct()
    )
    for start in range(0, len(names), MB_ARTIST_CHUNK_SIZE):
        chunk = names[start:start + MB_ARTIST_CHUNK_SIZE]
        logger.info(
            "Resolving MusicBrainz MBIDs for artists %d-%d of %d",
            start + 1,
            min(start + len(chunk), len(names)),
            len(names),
        )
        for name in chunk:
            try:
                mbid = search_mb_artist_mbid(name)
            except Exception as exc:
                logger.warning("MusicBrainz lookup crashed for %r: %s", name, exc)
                mbid = None
            time.sleep(MB_REQUEST_DELAY_SECONDS)
            if mbid:
                art, _ = Artist.objects.get_or_create(name=name)
                if not art.mbid:
                    art.mbid = mbid
                    art.save()
            else:
                # create without mbid to avoid re-querying next time
                Artist.objects.get_or_create(name=name)

    # Link TrackItems that now have an Artist row
    for ti in TrackItem.objects.filter(artist__isnull=True).exclude(artist_name_guess=""):
        try:
            ti.artist = Artist.objects.get(name=ti.artist_name_guess)
            ti.save()
        except Artist.DoesNotExist:
            pass

@shared_task
def build_snapshot():
    logger.info("Building snapshot…")
    mbids = (Artist.objects.exclude(mbid__isnull=True)
             .exclude(mbid__exact="")
             .filter(trackitem__blacklisted=False)
             .values_list("mbid", flat=True)
             .distinct())
    payload = [{"MusicBrainzId": mbid} for mbid in mbids]
    Snapshot.objects.create(payload=payload)
    logger.info("Snapshot created with %d items", len(payload))
    return len(payload)

@shared_task
def refresh_all_and_snapshot():
    refresh_playlists.delay()
    chain(resolve_missing_mbids.si(), build_snapshot.si(), import_unresolved_tracks_from_youtube.si()).delay()


def _sanitize_name(value: str) -> str:
    cleaned = "".join(ch for ch in (value or "") if ch.isalnum() or ch in (" ", "-", "_")).strip()
    return cleaned[:120] or "unknown"


def _download_track_media(video_id: str, artist: str, title: str):
    artist_dir_name = _sanitize_name(artist)
    video_dir = os.path.join(settings.YOUTUBE_FALLBACK_VIDEO_DIR, artist_dir_name)
    audio_dir = os.path.join(settings.YOUTUBE_FALLBACK_AUDIO_DIR, artist_dir_name)
    os.makedirs(video_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)

    safe_video_id = _sanitize_name(video_id)
    base = f"{_sanitize_name(artist)} - {_sanitize_name(title)} [{safe_video_id}]"
    url = f"https://www.youtube.com/watch?v={video_id}"
    video_path = os.path.join(video_dir, f"{base}.mp4")
    mp3_path = os.path.join(audio_dir, f"{base}.mp3")
    if os.path.exists(video_path) and os.path.exists(mp3_path):
        return video_path, mp3_path

    video_tpl = os.path.join(video_dir, f"{base}.%(ext)s")
    audio_tpl = os.path.join(audio_dir, f"{base}.%(ext)s")

    video_run = subprocess.run(
        ["yt-dlp", "-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4", "--print", "after_move:filepath", "-o", video_tpl, url],
        check=True,
        capture_output=True,
        text=True,
        timeout=settings.YOUTUBE_FALLBACK_DOWNLOAD_TIMEOUT,
    )
    audio_run = subprocess.run(
        ["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "mp3", "--print", "after_move:filepath", "-o", audio_tpl, url],
        check=True,
        capture_output=True,
        text=True,
        timeout=settings.YOUTUBE_FALLBACK_DOWNLOAD_TIMEOUT,
    )
    video_out = (video_run.stdout or "").strip().splitlines()
    audio_out = (audio_run.stdout or "").strip().splitlines()
    if video_out:
        video_path = video_out[-1]
    if audio_out:
        mp3_path = audio_out[-1]
    return video_path, mp3_path


@shared_task
def import_unresolved_tracks_from_youtube():
    if not settings.YOUTUBE_FALLBACK_ENABLE:
        return 0
    queryset = (
        TrackItem.objects.filter(blacklisted=False, artist__isnull=True)
        .exclude(video_id="")
        .exclude(fallback_jobs__status=FallbackImportJob.STATUS_DONE)
        .order_by("-published_at", "-id")[: settings.YOUTUBE_FALLBACK_MAX_PER_RUN]
    )
    imported = 0
    for ti in queryset:
        job, _ = FallbackImportJob.objects.get_or_create(track_item=ti)
        try:
            video_path, mp3_path = _download_track_media(ti.video_id, ti.artist_name_guess or ti.channel_title, ti.title)
            job.status = FallbackImportJob.STATUS_DONE
            job.video_path = video_path
            job.mp3_path = mp3_path
            job.last_error = ""
            job.save(update_fields=["status", "video_path", "mp3_path", "last_error", "updated_at"])
            imported += 1
        except Exception as exc:
            job.status = FallbackImportJob.STATUS_FAILED
            job.last_error = str(exc)[:2000]
            job.save(update_fields=["status", "last_error", "updated_at"])
            logger.exception("Fallback media import failed for track %s: %s", ti.id, exc)
    return imported
