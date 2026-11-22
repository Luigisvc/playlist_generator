import json
import xml.etree.ElementTree as ET

import pytest

from playlist_generator.exporters import (
    PATH_ABSOLUTE,
    ExportError,
    ExportOptions,
    export_playlist,
    sanitize_filename,
)
from playlist_generator.scanner import Track


def test_sanitize_filename():
    assert sanitize_filename('a/b:c*?"<>|') == "a_b_c______"
    assert sanitize_filename("   ") == "playlist"


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "Music"
    (root / "Artist" / "Album").mkdir(parents=True)
    tracks = []
    for i in range(3):
        path = root / "Artist" / "Album" / f"0{i} Música ção.flac"
        path.write_bytes(b"")
        tracks.append(Track(path=path, title=f"Faixa {i}", artist="Artista", album="Álbum",
                            duration=61.4))
    return root, tracks


def opts_for(root, dest, **kw):
    return ExportOptions(name="Minha lista", dest_dir=dest, music_root=root, **kw)


def entries_of(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if not line.startswith("#")]


def test_m3u_same_folder_relative(library):
    root, tracks = library
    path = export_playlist(tracks, "m3u8", opts_for(root, root))
    assert path == root / "Minha lista.m3u8"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1] == "#PLAYLIST:Minha lista"
    assert lines[2] == "#EXTINF:61,Artista - Faixa 0"
    assert lines[3] == "Artist/Album/00 Música ção.flac"


def test_m3u_dedicated_folder_relative_paths_resolve(library):
    root, tracks = library
    dest = root / "Playlists"
    path = export_playlist(tracks, "m3u", opts_for(root, dest))
    entries = entries_of(path)
    assert entries[0] == "../Artist/Album/00 Música ção.flac"
    assert (dest / entries[0]).resolve() == tracks[0].path.resolve()


def test_m3u_absolute_and_server_prefix(library):
    root, tracks = library
    path = export_playlist(tracks, "m3u8", opts_for(root, root, path_mode=PATH_ABSOLUTE))
    assert entries_of(path)[0] == str(tracks[0].path)

    path = export_playlist(
        tracks, "m3u8",
        opts_for(root, root, path_mode=PATH_ABSOLUTE, server_prefix="/music/"),
    )
    assert entries_of(path)[0] == "/music/Artist/Album/00 Música ção.flac"


def test_pls(library):
    root, tracks = library
    path = export_playlist(tracks, "pls", opts_for(root, root))
    text = path.read_text(encoding="utf-8")
    assert text.startswith("[playlist]\n")
    assert "File1=Artist/Album/00 Música ção.flac" in text
    assert "Title3=Artista - Faixa 2" in text
    assert "NumberOfEntries=3" in text
    assert "Version=2" in text


def test_xspf_is_valid_xml_with_encoded_locations(library):
    root, tracks = library
    path = export_playlist(tracks, "xspf", opts_for(root, root))
    tree = ET.parse(path)
    ns = {"x": "http://xspf.org/ns/0/"}
    locations = [e.text for e in tree.getroot().findall(".//x:location", ns)]
    assert len(locations) == 3
    assert locations[0] == "Artist/Album/00%20M%C3%BAsica%20%C3%A7%C3%A3o.flac"
    assert tree.getroot().find("x:title", ns).text == "Minha lista"
    assert tree.getroot().find(".//x:duration", ns).text == "61400"


def test_nsp_is_json_with_library_relative_filepaths(library):
    root, tracks = library
    path = export_playlist(tracks, "nsp", opts_for(root, root / "Playlists"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["name"] == "Minha lista"
    assert data["any"][0] == {"is": {"filepath": "Artist/Album/00 Música ção.flac"}}
    assert len(data["any"]) == 3


def test_nsp_too_large_raises(tmp_path):
    tracks = [Track(path=tmp_path / ("x" * 150 + f"{i}.flac")) for i in range(1000)]
    with pytest.raises(ExportError):
        export_playlist(tracks, "nsp", opts_for(tmp_path, tmp_path))


def test_export_errors(library, tmp_path):
    root, tracks = library
    with pytest.raises(ExportError):
        export_playlist([], "m3u", opts_for(root, root))
    with pytest.raises(ExportError):
        export_playlist(tracks, "doc", opts_for(root, root))
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(ExportError):
        export_playlist(tracks, "m3u", opts_for(root, blocker / "sub"))
