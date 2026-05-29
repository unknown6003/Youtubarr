import json
from django.utils import timezone
from django.db import transaction, DatabaseError, connection

from django.core.management.base import BaseCommand

from youtubarr.models import Artist, Snapshot, TrackItem, PipelineRun
from youtubarr.tasks import (
    build_snapshot,
    import_unresolved_tracks_from_youtube,
    normalize_artist_guesses,
    refresh_playlists,
    resolve_missing_mbids,
)


class Command(BaseCommand):
    help = "Run full Youtubarr pipeline and print compact JSON diagnostics."

    def handle(self, *args, **options):
        run = PipelineRun.objects.create(started_at=timezone.now())
        before_tracks = TrackItem.objects.count()
        before_artists = Artist.objects.count()
        before_mbid_artists = Artist.objects.exclude(mbid__isnull=True).exclude(mbid__exact="").count()
        refresh_count = 0
        normalized_count = 0
        snapshot_count = 0
        fallback_count = 0
        status = PipelineRun.STATUS_FAILED
        last_error = "unexpected pipeline failure"
        try:
            refresh_count = refresh_playlists()
            normalized_count = normalize_artist_guesses()
            resolve_missing_mbids()
            snapshot_count = build_snapshot()
            fallback_count = import_unresolved_tracks_from_youtube()
            status = PipelineRun.STATUS_OK
            last_error = ""
        except Exception as exc:
            last_error = str(exc)[:2000]
        finally:
            try:
                with transaction.atomic():
                    after_tracks = TrackItem.objects.count()
                    after_artists = Artist.objects.count()
                    after_mbid_artists = Artist.objects.exclude(mbid__isnull=True).exclude(mbid__exact="").count()
                    latest = Snapshot.objects.order_by("-created_at").first()
                    payload_count = len(latest.payload) if latest else 0

                    run.finished_at = timezone.now()
                    run.status = status
                    run.refresh_count = refresh_count
                    run.normalized_count = normalized_count
                    run.snapshot_count = snapshot_count
                    run.fallback_count = fallback_count
                    run.tracks_before = before_tracks
                    run.tracks_after = after_tracks
                    run.artists_before = before_artists
                    run.artists_after = after_artists
                    run.artists_with_mbid_before = before_mbid_artists
                    run.artists_with_mbid_after = after_mbid_artists
                    run.latest_payload_count = payload_count
                    run.last_error = last_error
                    run.save()
            except DatabaseError:
                connection.close()
                run.finished_at = timezone.now()
                run.status = PipelineRun.STATUS_FAILED
                run.last_error = (last_error or "pipeline run failed; db error while persisting metrics")[:2000]
                run.save(update_fields=["finished_at", "status", "last_error"])

        latest = Snapshot.objects.order_by("-created_at").first()
        payload_count = len(latest.payload) if latest else 0

        payload = {
            "run_id": run.id,
            "status": run.status,
            "last_error": run.last_error,
            "refresh_count": refresh_count,
            "normalized_count": normalized_count,
            "snapshot_count": snapshot_count,
            "fallback_count": fallback_count,
            "tracks_before": before_tracks,
            "tracks_after": after_tracks,
            "artists_before": before_artists,
            "artists_after": after_artists,
            "artists_with_mbid_before": before_mbid_artists,
            "artists_with_mbid_after": after_mbid_artists,
            "latest_payload_count": payload_count,
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=True))
