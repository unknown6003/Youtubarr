import json
import pytest
from django.conf import settings
from youtubarr.models import Snapshot
from tests.factories import PlaylistFactory

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
