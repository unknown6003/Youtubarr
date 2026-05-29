from youtubarr.utils import guess_artist_from_title, mb_artist_candidates

def test_guess_artist_basic():
    assert guess_artist_from_title("Artist - Song", "X") == "Artist"

def test_guess_from_topic_channel():
    assert guess_artist_from_title("Weird Title", "Foo - Topic") == "Foo"

def test_guess_empty():
    assert guess_artist_from_title("Song Name Only", "Channel") == ""


def test_mb_artist_candidates_split_duet():
    assert mb_artist_candidates("Foo x Bar")[0] == "Foo x Bar"
    assert "Foo" in mb_artist_candidates("Foo x Bar")
    assert "Bar" in mb_artist_candidates("Foo x Bar")
