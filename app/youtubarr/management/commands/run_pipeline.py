import json

from django.core.management.base import BaseCommand

from youtubarr.models import Artist, Snapshot, TrackItem
from youtubarr.tasks import (
    build_snapshot,
    import_unresolved_tracks_from_youtube,
    refresh_playlists,
    resolve_missing_mbids,
)


class Command(BaseCommand):
    help = "Run full Youtubarr pipeline and print compact JSON diagnostics."

    def handle(self, *args, **options):
        before_tracks = TrackItem.objects.count()
        before_artists = Artist.objects.count()
        before_mbid_artists = Artist.objects.exclude(mbid__isnull=True).exclude(mbid__exact="").count()

        refresh_count = refresh_playlists()
        resolve_missing_mbids()
        snapshot_count = build_snapshot()
        fallback_count = import_unresolved_tracks_from_youtube()

        after_tracks = TrackItem.objects.count()
        after_artists = Artist.objects.count()
        after_mbid_artists = Artist.objects.exclude(mbid__isnull=True).exclude(mbid__exact="").count()
        latest = Snapshot.objects.order_by("-created_at").first()
        payload_count = len(latest.payload) if latest else 0

        payload = {
            "refresh_count": refresh_count,
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
