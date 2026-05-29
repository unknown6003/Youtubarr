import json
import pytest
from django.conf import settings
from youtubarr.models import Snapshot, FallbackImportJob, TrackItem
from tests.factories import PlaylistFactory
from unittest.mock import patch

@pytest.mark.django_db
def test_lidarr_requires_token(client, settings):
    settings.LIDARR_TOKEN = "secret"
    Snapshot.objects.create(payload=[])
    r = client.get("/api/v1/lidarr")
    assert r.status_code == 403
    r = client.get("/api/v1/lidarr?token=secret")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.django_db
def test_force_sync_endpoint(client, settings):
    settings.YOUTUBE_API_KEY = ""
    PlaylistFactory(playlist_id="PL_TEST_123456", enabled=True)
    r = client.post("/playlists/force-sync/")
    assert r.status_code == 302
    assert r["Location"].endswith("/playlists/")


@pytest.mark.django_db
def test_fallback_imports_page_loads(client, settings):
    settings.YOUTUBE_FALLBACK_ENABLE = False
    r = client.get("/fallback-imports/")
    assert r.status_code == 200
    assert b"Fallback Imports" in r.content


@pytest.mark.django_db
def test_trigger_fallback_imports_disabled(client, settings):
    settings.YOUTUBE_FALLBACK_ENABLE = False
    r = client.post("/fallback-imports/run/")
    assert r.status_code == 302
    assert r["Location"].endswith("/fallback-imports/")


@pytest.mark.django_db
def test_trigger_fallback_imports_enabled(client, settings):
    settings.YOUTUBE_FALLBACK_ENABLE = True
    with patch("youtubarr.views.import_unresolved_tracks_from_youtube.delay") as delayed:
        r = client.post("/fallback-imports/run/")
    assert r.status_code == 302
    assert r["Location"].endswith("/fallback-imports/")
    delayed.assert_called_once()


@pytest.mark.django_db
def test_diagnostics_requires_token(client, settings):
    settings.LIDARR_TOKEN = "secret"
    r = client.get("/api/v1/diagnostics")
    assert r.status_code == 403


@pytest.mark.django_db
def test_diagnostics_payload(client, settings):
    settings.LIDARR_TOKEN = "secret"
    settings.YOUTUBE_API_KEY = "key"
    settings.YOUTUBE_OAUTH_ACCESS_TOKEN = "token"
    settings.YOUTUBE_OAUTH_CLIENT_ID = "cid"
    pl = PlaylistFactory(playlist_id="PL_TEST_DX", enabled=True)
    ti = TrackItem.objects.create(
        playlist=pl,
        video_id="viddx01",
        title="Artist - Song",
        channel_title="Artist - Topic",
        artist_name_guess="Artist",
    )
    Snapshot.objects.create(payload=[{"MusicBrainzId": "11111111-1111-1111-1111-111111111111"}])
    FallbackImportJob.objects.create(track_item=ti, status=FallbackImportJob.STATUS_DONE)

    r = client.get("/api/v1/diagnostics?token=secret")
    assert r.status_code == 200
    body = r.json()
    assert body["oauth_ready"] is True
    assert body["api_key_ready"] is True
    assert body["playlists_total"] >= 1
    assert body["snapshot_payload_count"] == 1
    assert body["fallback_jobs_done"] >= 1
