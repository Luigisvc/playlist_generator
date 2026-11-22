import random
from pathlib import Path

from playlist_generator.generator import generate_playlist
from playlist_generator.scanner import Track, find_audio_files, read_track


def make_tracks(spec):
    """spec: lista de (artista, álbum). Cria faixas fictícias."""
    return [
        Track(path=Path(f"/music/{artist or 'x'}/{i}.flac"), title=f"t{i}", artist=artist,
              album=album, duration=100.0)
        for i, (artist, album) in enumerate(spec)
    ]


def test_generator_uses_all_tracks_without_duplicates():
    tracks = make_tracks([("A", "a1")] * 5 + [("B", "b1")] * 5 + [("C", "c1")] * 5)
    result = generate_playlist(tracks, 0, random.Random(1))
    assert len(result) == 15
    assert len({id(t) for t in result}) == 15


def test_generator_respects_count():
    tracks = make_tracks([("A", "a")] * 10 + [("B", "b")] * 10)
    assert len(generate_playlist(tracks, 7, random.Random(2))) == 7
    assert len(generate_playlist(tracks, 999, random.Random(2))) == 20


def test_generator_avoids_same_artist_in_a_row():
    tracks = make_tracks([("A", "a")] * 6 + [("B", "b")] * 6 + [("C", "c")] * 6)
    for seed in range(50):
        result = generate_playlist(tracks, 0, random.Random(seed))
        for first, second in zip(result, result[1:]):
            assert first.artist_key != second.artist_key


def test_generator_empty_and_single_artist():
    assert generate_playlist([], 5) == []
    tracks = make_tracks([("A", "a")] * 4)
    assert len(generate_playlist(tracks, 0, random.Random(3))) == 4


def test_generator_unknown_artists_are_unrestricted():
    tracks = make_tracks([("", "")] * 5)
    assert len(generate_playlist(tracks, 0, random.Random(4))) == 5


def test_find_audio_files_filters_extensions(tmp_path):
    (tmp_path / "sub").mkdir()
    for name in ("a.flac", "b.MP3", "sub/c.wav", "d.txt", "e.jpg", ".hidden.mp3"):
        (tmp_path / name).write_bytes(b"")
    names = sorted(p.name for p in find_audio_files(tmp_path))
    assert names == ["a.flac", "b.MP3", "c.wav"]


def test_read_track_with_invalid_file_does_not_raise(tmp_path):
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"not audio")
    track = read_track(bad)
    assert track.path == bad
    assert track.display_title == "broken"
