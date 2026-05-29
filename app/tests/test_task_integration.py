import json
import pytest
import responses
from django.conf import settings
from freezegun import freeze_time
from youtubarr.models import Snapshot, Artist, TrackItem
from youtubarr.tasks import refresh_playlists, resolve_missing_mbids, build_snapshot, _get_oauth_bundle, search_mb_artist_mbid
from tests.factories import PlaylistFactory

YT_ITEMS = {
  "items": [
    {"snippet": {
      "position": 0,
      "title": "Foo - Bar",
      "channelTitle": "Foo - Topic",
      "publishedAt": "2024-01-01T00:00:00Z",
      "resourceId": {"videoId": "abc123"}
    }},
    {"snippet": {
      "position": 1,
      "title": "Baz - Qux",
      "channelTitle": "Baz - Topic",
      "publishedAt": "2024-01-02T00:00:00Z",
      "resourceId": {"videoId": "def456"}
    }}
  ]
}

YT_META = {
  "items": [{
    "snippet": {"title": "My Playlist", "channelTitle": "Owner"}
  }]
}

MB_RESP_FOO = {"artists": [{"id": "11111111-1111-1111-1111-111111111111"}]}
MB_RESP_BAZ = {"artists": [{"id": "22222222-2222-2222-2222-222222222222"}]}

@freeze_time("2025-01-01")
@responses.activate
@pytest.mark.django_db
def test_full_refresh_and_snapshot(settings):
    settings.YOUTUBE_API_KEY = "TESTKEY"
    settings.MB_USER_AGENT = "tests/1.0 (test@example.com)"

    pl = PlaylistFactory(playlist_id="PL_TEST")

    # Playlist meta + items
    responses.add(responses.GET,
                  "https://www.googleapis.com/youtube/v3/playlists",
                  json=YT_META, status=200)
    responses.add(responses.GET,
                  "https://www.googleapis.com/youtube/v3/playlistItems",
                  json=YT_ITEMS, status=200)

    # MusicBrainz lookups (Foo, Baz)
    responses.add(responses.GET,
                  "https://musicbrainz.org/ws/2/artist/",
                  match=[responses.matchers.query_param_matcher(
                      {"query": 'artist:"Foo"', "fmt": "json"})],
                  json=MB_RESP_FOO, status=200)
    responses.add(responses.GET,
                  "https://musicbrainz.org/ws/2/artist/",
                  match=[responses.matchers.query_param_matcher(
                      {"query": 'artist:"Baz"', "fmt": "json"})],
                  json=MB_RESP_BAZ, status=200)

    # 1) fetch playlist items
    assert refresh_playlists() == 2
    assert TrackItem.objects.count() == 2

    # 2) resolve mbids
    resolve_missing_mbids()
    assert Artist.objects.exclude(mbid="").count() == 2

    # 3) snapshot
    build_snapshot()
    snap = Snapshot.objects.order_by("-created_at").first()
    assert snap and {"MusicBrainzId": "11111111-1111-1111-1111-111111111111"} in snap.payload
    assert {"MusicBrainzId": "22222222-2222-2222-2222-222222222222"} in snap.payload


@responses.activate
@pytest.mark.django_db
def test_playlist_fetch_uses_oauth_and_refresh(settings):
    settings.YOUTUBE_API_KEY = ""
    settings.YOUTUBE_OAUTH_ACCESS_TOKEN = "expired-token"
    settings.YOUTUBE_OAUTH_REFRESH_TOKEN = "refresh-token"
    settings.YOUTUBE_OAUTH_CLIENT_ID = "client-id"
    settings.YOUTUBE_OAUTH_CLIENT_SECRET = "client-secret"

    pl = PlaylistFactory(playlist_id="PL_TEST")

    responses.add(
        responses.GET,
        "https://www.googleapis.com/youtube/v3/playlists",
        status=401,
        json={"error": {"message": "Expired token"}},
    )
    responses.add(
        responses.POST,
        "https://oauth2.googleapis.com/token",
        status=200,
        json={"access_token": "fresh-token"},
    )
    responses.add(
        responses.GET,
        "https://www.googleapis.com/youtube/v3/playlists",
        status=200,
        json=YT_META,
    )
    responses.add(
        responses.GET,
        "https://www.googleapis.com/youtube/v3/playlistItems",
        status=200,
        json=YT_ITEMS,
    )

    assert refresh_playlists() == 2
    assert TrackItem.objects.count() == 2


def test_oauth_json_bundle_parsing(settings):
    settings.YOUTUBE_OAUTH_JSON = json.dumps(
        {
            "access_token": "at-json",
            "refresh_token": "rt-json",
            "client_id": "cid-json",
            "client_secret": "csec-json",
        }
    )
    settings.YOUTUBE_OAUTH_ACCESS_TOKEN = "at-env"
    bundle = _get_oauth_bundle()
    assert bundle["access_token"] == "at-json"
    assert bundle["refresh_token"] == "rt-json"
    assert bundle["client_id"] == "cid-json"
    assert bundle["client_secret"] == "csec-json"


def test_oauth_json_non_object_fallbacks_to_env(settings):
    settings.YOUTUBE_OAUTH_JSON = json.dumps(["not-an-object"])
    settings.YOUTUBE_OAUTH_ACCESS_TOKEN = "at-env"
    settings.YOUTUBE_OAUTH_REFRESH_TOKEN = "rt-env"
    settings.YOUTUBE_OAUTH_CLIENT_ID = "cid-env"
    settings.YOUTUBE_OAUTH_CLIENT_SECRET = "csec-env"
    bundle = _get_oauth_bundle()
    assert bundle["access_token"] == "at-env"
    assert bundle["refresh_token"] == "rt-env"
    assert bundle["client_id"] == "cid-env"
    assert bundle["client_secret"] == "csec-env"


@responses.activate
def test_mb_lookup_uses_candidate_split():
    responses.add(
        responses.GET,
        "https://musicbrainz.org/ws/2/artist/",
        match=[responses.matchers.query_param_matcher({"query": 'artist:"Foo x Bar"', "fmt": "json"})],
        json={"artists": []},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://musicbrainz.org/ws/2/artist/",
        match=[responses.matchers.query_param_matcher({"query": 'artist:"Foo"', "fmt": "json"})],
        json={"artists": [{"id": "33333333-3333-3333-3333-333333333333"}]},
        status=200,
    )
    assert search_mb_artist_mbid("Foo x Bar") == "33333333-3333-3333-3333-333333333333"
