import pytest
from unittest.mock import patch
from types import SimpleNamespace
import subprocess

from youtubarr.models import TrackItem, FallbackImportJob
from youtubarr.tasks import import_unresolved_tracks_from_youtube, _sanitize_name
from tests.factories import PlaylistFactory


@pytest.mark.django_db
def test_import_unresolved_tracks_creates_done_job(settings, tmp_path):
    settings.YOUTUBE_FALLBACK_ENABLE = True
    video_dir = tmp_path / "videos"
    audio_dir = tmp_path / "audio"
    video_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    settings.YOUTUBE_FALLBACK_VIDEO_DIR = str(video_dir)
    settings.YOUTUBE_FALLBACK_AUDIO_DIR = str(audio_dir)
    settings.YOUTUBE_FALLBACK_MAX_PER_RUN = 10

    pl = PlaylistFactory()
    ti = TrackItem.objects.create(
        playlist=pl,
        video_id="abc123xyz00",
        title="Foo - Bar",
        channel_title="Foo - Topic",
        artist_name_guess="Foo",
    )

    with patch("youtubarr.tasks.subprocess.run") as run:
        run.side_effect = [
            SimpleNamespace(returncode=0, stdout=f"{tmp_path}/videos/file.mp4\n"),
            SimpleNamespace(returncode=0, stdout=f"{tmp_path}/audio/file.mp3\n"),
        ]
        count = import_unresolved_tracks_from_youtube()

    assert count == 1
    job = FallbackImportJob.objects.get(track_item=ti)
    assert job.status == FallbackImportJob.STATUS_DONE
    assert job.video_path.endswith(".mp4")
    assert job.mp3_path.endswith(".mp3")


@pytest.mark.django_db
def test_import_unresolved_tracks_skips_existing_files(settings, tmp_path):
    settings.YOUTUBE_FALLBACK_ENABLE = True
    video_root = tmp_path / "videos"
    audio_root = tmp_path / "audio"
    video_root.mkdir(parents=True, exist_ok=True)
    audio_root.mkdir(parents=True, exist_ok=True)
    settings.YOUTUBE_FALLBACK_VIDEO_DIR = str(video_root)
    settings.YOUTUBE_FALLBACK_AUDIO_DIR = str(audio_root)
    settings.YOUTUBE_FALLBACK_MAX_PER_RUN = 10

    pl = PlaylistFactory()
    ti = TrackItem.objects.create(
        playlist=pl,
        video_id="abc123xyz00",
        title="Foo - Bar",
        channel_title="Foo - Topic",
        artist_name_guess="Foo",
    )
    artist_dir = _sanitize_name("Foo")
    base = f"{_sanitize_name('Foo')} - {_sanitize_name('Foo - Bar')} [{_sanitize_name('abc123xyz00')}]"
    existing_video = video_root / artist_dir / f"{base}.mp4"
    existing_mp3 = audio_root / artist_dir / f"{base}.mp3"
    existing_video.parent.mkdir(parents=True, exist_ok=True)
    existing_mp3.parent.mkdir(parents=True, exist_ok=True)
    existing_video.write_text("video")
    existing_mp3.write_text("audio")

    with patch("youtubarr.tasks.subprocess.run") as run:
        count = import_unresolved_tracks_from_youtube()

    assert count == 1
    run.assert_not_called()
    job = FallbackImportJob.objects.get(track_item=ti)
    assert job.status == FallbackImportJob.STATUS_DONE
    assert job.video_path == str(existing_video)
    assert job.mp3_path == str(existing_mp3)


@pytest.mark.django_db
def test_import_unresolved_tracks_retries_then_succeeds(settings, tmp_path):
    settings.YOUTUBE_FALLBACK_ENABLE = True
    settings.YOUTUBE_FALLBACK_DOWNLOAD_RETRIES = 2
    settings.YOUTUBE_FALLBACK_DOWNLOAD_BACKOFF_SECONDS = 0.01
    video_dir = tmp_path / "videos"
    audio_dir = tmp_path / "audio"
    video_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    settings.YOUTUBE_FALLBACK_VIDEO_DIR = str(video_dir)
    settings.YOUTUBE_FALLBACK_AUDIO_DIR = str(audio_dir)

    pl = PlaylistFactory()
    ti = TrackItem.objects.create(
        playlist=pl,
        video_id="retry123",
        title="Retry Artist - Retry Song",
        channel_title="Retry Artist - Topic",
        artist_name_guess="Retry Artist",
    )
    with patch("youtubarr.tasks.subprocess.run") as run:
        run.side_effect = [
            subprocess.CalledProcessError(returncode=1, cmd="yt-dlp"),
            SimpleNamespace(returncode=0, stdout=f"{tmp_path}/videos/file.mp4\n"),
            SimpleNamespace(returncode=0, stdout=f"{tmp_path}/audio/file.mp3\n"),
        ]
        count = import_unresolved_tracks_from_youtube()

    assert count == 1
    job = FallbackImportJob.objects.get(track_item=ti)
    assert job.status == FallbackImportJob.STATUS_DONE
