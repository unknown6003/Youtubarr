import json
from unittest.mock import patch

import pytest
from django.core.management import call_command
from io import StringIO
from youtubarr.models import PipelineRun


@pytest.mark.django_db
def test_run_pipeline_command_outputs_json():
    out = StringIO()
    with patch("youtubarr.management.commands.run_pipeline.refresh_playlists", return_value=7), \
        patch("youtubarr.management.commands.run_pipeline.normalize_artist_guesses", return_value=5), \
        patch("youtubarr.management.commands.run_pipeline.resolve_missing_mbids", return_value=None), \
        patch("youtubarr.management.commands.run_pipeline.build_snapshot", return_value=3), \
        patch("youtubarr.management.commands.run_pipeline.import_unresolved_tracks_from_youtube", return_value=2):
        call_command("run_pipeline", stdout=out)
    payload = json.loads(out.getvalue().strip())
    assert payload["status"] == "ok"
    assert payload["refresh_count"] == 7
    assert payload["normalized_count"] == 5
    assert payload["snapshot_count"] == 3
    assert payload["fallback_count"] == 2
    run = PipelineRun.objects.order_by("-id").first()
    assert run is not None
    assert run.status == PipelineRun.STATUS_OK


@pytest.mark.django_db
def test_run_pipeline_command_outputs_failed_json():
    out = StringIO()
    with patch("youtubarr.management.commands.run_pipeline.refresh_playlists", side_effect=RuntimeError("boom")):
        call_command("run_pipeline", stdout=out)
    payload = json.loads(out.getvalue().strip())
    assert payload["status"] == "failed"
    assert "boom" in payload["last_error"]
