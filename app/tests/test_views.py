import json
import pytest
from django.conf import settings
from youtubarr.models import Snapshot, FallbackImportJob, TrackItem, PipelineRun
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
    PipelineRun.objects.create(status=PipelineRun.STATUS_OK, refresh_count=1, snapshot_count=1)

    r = client.get("/api/v1/diagnostics?token=secret")
    assert r.status_code == 200
    body = r.json()
    assert body["oauth_ready"] is True
    assert body["api_key_ready"] is True
    assert body["playlists_total"] >= 1
    assert body["snapshot_payload_count"] == 1
    assert body["fallback_jobs_done"] >= 1
    assert body["last_pipeline_run"] is not None
    assert body["last_pipeline_run"]["status"] == "ok"
    assert body["pipeline_running"] is False


@pytest.mark.django_db
def test_trigger_pipeline_requires_token(client, settings):
    settings.LIDARR_TOKEN = "secret"
    r = client.post("/api/v1/pipeline/trigger")
    assert r.status_code == 403


@pytest.mark.django_db
def test_trigger_pipeline_queues_task(client, settings):
    settings.LIDARR_TOKEN = "secret"
    with patch("youtubarr.views.refresh_all_and_snapshot.delay") as delayed:
        r = client.post("/api/v1/pipeline/trigger?token=secret")
    assert r.status_code == 200
    assert r.json()["queued"] is True
    delayed.assert_called_once()


@pytest.mark.django_db
def test_trigger_pipeline_conflict_when_running(client, settings):
    settings.LIDARR_TOKEN = "secret"
    PipelineRun.objects.create(status=PipelineRun.STATUS_RUNNING)
    r = client.post("/api/v1/pipeline/trigger?token=secret")
    assert r.status_code == 409
    body = r.json()
    assert body["queued"] is False


@pytest.mark.django_db
def test_pipeline_runs_requires_token(client, settings):
    settings.LIDARR_TOKEN = "secret"
    r = client.get("/api/v1/pipeline/runs")
    assert r.status_code == 403


@pytest.mark.django_db
def test_pipeline_runs_payload(client, settings):
    settings.LIDARR_TOKEN = "secret"
    PipelineRun.objects.create(status=PipelineRun.STATUS_OK, refresh_count=3, snapshot_count=2, latest_payload_count=2)
    r = client.get("/api/v1/pipeline/runs?token=secret")
    assert r.status_code == 200
    payload = r.json()
    assert isinstance(payload, list)
    assert payload
    assert payload[0]["status"] == "ok"


@pytest.mark.django_db
def test_fallback_jobs_requires_token(client, settings):
    settings.LIDARR_TOKEN = "secret"
    r = client.get("/api/v1/fallback/jobs")
    assert r.status_code == 403


@pytest.mark.django_db
def test_fallback_jobs_filter(client, settings):
    settings.LIDARR_TOKEN = "secret"
    pl = PlaylistFactory(playlist_id="PL_FB_FILTER", enabled=True)
    ti = TrackItem.objects.create(
        playlist=pl,
        video_id="fbvid001",
        title="FB Artist - FB Song",
        channel_title="FB Artist - Topic",
        artist_name_guess="FB Artist",
    )
    FallbackImportJob.objects.create(track_item=ti, status=FallbackImportJob.STATUS_FAILED)
    r = client.get("/api/v1/fallback/jobs?token=secret&status=failed")
    assert r.status_code == 200
    payload = r.json()
    assert payload
    assert payload[0]["status"] == "failed"
    assert payload[0]["can_retry"] is True


@pytest.mark.django_db
def test_retry_fallback_jobs_resets_failed_and_queues(client, settings):
    settings.LIDARR_TOKEN = "secret"
    pl = PlaylistFactory(playlist_id="PL_FB_RETRY", enabled=True)
    ti = TrackItem.objects.create(
        playlist=pl,
        video_id="fbvid002",
        title="Retry Artist - Retry Song",
        channel_title="Retry Artist - Topic",
        artist_name_guess="Retry Artist",
    )
    job = FallbackImportJob.objects.create(
        track_item=ti,
        status=FallbackImportJob.STATUS_FAILED,
        last_error="boom",
    )
    with patch("youtubarr.views.import_unresolved_tracks_from_youtube.delay") as delayed:
        r = client.post("/api/v1/fallback/retry?token=secret")
    assert r.status_code == 200
    body = r.json()
    assert body["queued"] is True
    assert body["reset_jobs"] >= 1
    delayed.assert_called_once()
    job.refresh_from_db()
    assert job.status == FallbackImportJob.STATUS_PENDING
    assert job.last_error == ""


@pytest.mark.django_db
def test_retry_fallback_job_ids_requires_token(client, settings):
    settings.LIDARR_TOKEN = "secret"
    r = client.post("/api/v1/fallback/retry-ids?ids=1,2")
    assert r.status_code == 403


@pytest.mark.django_db
def test_retry_fallback_job_ids_bad_ids(client, settings):
    settings.LIDARR_TOKEN = "secret"
    r = client.post("/api/v1/fallback/retry-ids?token=secret&ids=foo,bar")
    assert r.status_code == 400
    assert r.json()["queued"] is False


@pytest.mark.django_db
def test_retry_fallback_job_ids_resets_selected_jobs(client, settings):
    settings.LIDARR_TOKEN = "secret"
    pl = PlaylistFactory(playlist_id="PL_FB_RETRY_IDS", enabled=True)
    ti1 = TrackItem.objects.create(
        playlist=pl,
        video_id="fbvid101",
        title="Retry Artist - Retry Song 1",
        channel_title="Retry Artist - Topic",
        artist_name_guess="Retry Artist",
    )
    ti2 = TrackItem.objects.create(
        playlist=pl,
        video_id="fbvid102",
        title="Retry Artist - Retry Song 2",
        channel_title="Retry Artist - Topic",
        artist_name_guess="Retry Artist",
    )
    j1 = FallbackImportJob.objects.create(track_item=ti1, status=FallbackImportJob.STATUS_FAILED, last_error="e1")
    j2 = FallbackImportJob.objects.create(track_item=ti2, status=FallbackImportJob.STATUS_FAILED, last_error="e2")
    with patch("youtubarr.views.import_unresolved_tracks_from_youtube.delay") as delayed:
        r = client.post(f"/api/v1/fallback/retry-ids?token=secret&ids={j1.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["queued"] is True
    assert body["reset_jobs"] == 1
    delayed.assert_called_once()
    j1.refresh_from_db()
    j2.refresh_from_db()
    assert j1.status == FallbackImportJob.STATUS_PENDING
    assert j1.last_error == ""
    assert j2.status == FallbackImportJob.STATUS_FAILED
