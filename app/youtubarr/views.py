from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.contrib import messages
from django.conf import settings
from urllib.parse import urlparse, parse_qs
from .models import AppSettings, Playlist, TrackItem, Snapshot, FallbackImportJob
from .tasks import fetch_playlist_items, import_unresolved_tracks_from_youtube


def _normalize_playlist_id(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if value == "LM":
        return value
    if "youtube.com" in value or "youtu.be" in value:
        parsed = urlparse(value)
        qs = parse_qs(parsed.query)
        list_values = qs.get("list") or []
        if list_values:
            return list_values[0].strip()
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            return parts[-1].strip()
    return value

def settings_view(request):
    s = AppSettings.load()
    if request.method == "POST":
        s.youtube_api_key = request.POST.get("youtube_api_key","").strip()
        s.save()
        messages.success(request, "YouTube API key updated.")
        return redirect("settings")
    return render(request, "settings.html", {"settings": s, "env_has_key": bool(settings.YOUTUBE_API_KEY),"lidarr_token": getattr(settings, "LIDARR_TOKEN", None)})

@require_http_methods(["GET","POST"])
def playlists_view(request):
    if request.method == "POST":
        pid = _normalize_playlist_id(request.POST.get("playlist_id"))
        if pid:
            pl, created = Playlist.objects.get_or_create(playlist_id=pid)
            try:
                fetched = fetch_playlist_items(pl)
                status = "Added" if created else "Updated"
                messages.success(request, f"{status} {pid}. Synced {fetched} items.")
            except Exception as exc:
                messages.error(request, f"Saved {pid}, but sync failed: {exc}")
        else:
            messages.error(request, "Playlist ID required.")
        return redirect("playlists")
    pls = Playlist.objects.all().order_by("-last_synced","playlist_id")
    return render(request, "playlists.html", {"playlists": pls})

def items_view(request):
    items = (TrackItem.objects
             .select_related("playlist","artist")
             .order_by("-published_at","-id")[:500])
    return render(request, "items.html", {"items": items})


def fallback_imports_view(request):
    jobs = (
        FallbackImportJob.objects.select_related("track_item", "track_item__playlist")
        .order_by("-updated_at", "-id")[:500]
    )
    return render(
        request,
        "fallback_imports.html",
        {
            "jobs": jobs,
            "fallback_enabled": bool(getattr(settings, "YOUTUBE_FALLBACK_ENABLE", False)),
        },
    )


@require_http_methods(["POST"])
def trigger_fallback_imports_view(request):
    if not getattr(settings, "YOUTUBE_FALLBACK_ENABLE", False):
        messages.error(request, "Fallback import is disabled. Set YOUTUBE_FALLBACK_ENABLE=true.")
        return redirect("fallback-imports")
    import_unresolved_tracks_from_youtube.delay()
    messages.success(request, "Fallback import job queued.")
    return redirect("fallback-imports")


@require_http_methods(["POST"])
def force_sync_playlists_view(request):
    total = 0
    synced_playlists = 0
    for pl in Playlist.objects.filter(enabled=True):
        try:
            total += fetch_playlist_items(pl)
            synced_playlists += 1
        except Exception as exc:
            messages.error(request, f"Sync failed for {pl.playlist_id}: {exc}")
    if synced_playlists:
        messages.success(request, f"Force sync complete. Synced {total} items across {synced_playlists} playlists.")
    else:
        messages.info(request, "No enabled playlists to sync.")
    return redirect("playlists")

# ---- HTMX helpers ----

def item_row(request, item_id):
    it = get_object_or_404(TrackItem.objects.select_related("playlist","artist"), id=item_id)
    return render(request, "partials/item_row.html", {"it": it})

@require_http_methods(["POST"])
def toggle_blacklist(request, item_id):
    it = get_object_or_404(TrackItem, id=item_id)
    # checkbox sends "on" when checked; missing when unchecked
    val = request.POST.get("blacklisted") == "on"
    if it.blacklisted != val:
        it.blacklisted = val
        it.save(update_fields=["blacklisted"])
    return item_row(request, item_id)

@require_http_methods(["POST"])
def edit_item(request, item_id):
    it = get_object_or_404(TrackItem, id=item_id)
    title = request.POST.get("title", it.title)
    artist_guess = request.POST.get("artist_name_guess", it.artist_name_guess)
    changed = []
    if title != it.title:
        it.title = title
        changed.append("title")
    if artist_guess != it.artist_name_guess:
        it.artist_name_guess = artist_guess
        changed.append("artist_name_guess")
    if changed:
        it.save(update_fields=changed)
    return item_row(request, item_id)

@require_http_methods(["POST"])
def delete_item(request, item_id):
    it = get_object_or_404(TrackItem, id=item_id)
    it.delete()
    # HTMX: tell client to remove the row
    return HttpResponse(status=204, headers={"HX-Trigger": "item-deleted"})

def healthz(request):
    return HttpResponse("ok")

def lidarr_youtubarr_view(request):
    # token via ?token=... or X-Api-Key header
    token = request.GET.get("token") or request.headers.get("X-Api-Key")
    if not (settings.LIDARR_TOKEN and token == settings.LIDARR_TOKEN):
        return HttpResponseForbidden("missing/invalid token")
    snap = Snapshot.objects.order_by("-created_at").first()
    return JsonResponse(snap.payload if snap else [], safe=False)

def add_liked_music(request):
    if request.method == "POST":
        if not settings.YTMUSIC_COOKIE_JSON:
            return HttpResponse("YTMUSIC_COOKIE_JSON not configured", status=500)
        Playlist.objects.get_or_create(
            playlist_id="LM",
            defaults={"title": "Liked Music", "channel_title": "YouTube Music"}
        )
        return redirect("playlists")
