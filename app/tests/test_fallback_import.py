import pytest
from unittest.mock import patch
from types import SimpleNamespace

from youtubarr.models import TrackItem, FallbackImportJob
from youtubarr.tasks import import_unresolved_tracks_from_youtube
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
