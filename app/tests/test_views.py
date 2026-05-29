import json
import pytest
from django.conf import settings
from youtubarr.models import Snapshot
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
