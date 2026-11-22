"""Varredura de uma pasta de músicas e leitura das tags."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import mutagen

AUDIO_EXTENSIONS = frozenset(
    {
        ".flac",
        ".mp3",
        ".wav",
        ".ogg",
        ".oga",
        ".opus",
        ".m4a",
        ".m4b",
        ".aac",
        ".wma",
        ".ape",
        ".wv",
        ".aiff",
        ".aif",
        ".alac",
        ".mpc",
    }
)


@dataclass(eq=False)
class Track:
    """Uma faixa de áudio. A identidade é por objeto (eq=False)."""

    path: Path
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    duration: float = 0.0  # segundos

    @property
    def display_title(self) -> str:
        return self.title or self.path.stem

    @property
    def artist_key(self) -> str:
        """Chave de comparação do artista ('' = desconhecido)."""
        return (self.artist or self.album_artist).strip().casefold()

    @property
    def album_key(self) -> str:
        """Chave de comparação do álbum ('' = desconhecido)."""
        return self.album.strip().casefold()


def _first(tags, *keys: str) -> str:
    """Retorna o primeiro valor de texto não vazio encontrado para as chaves."""
    if tags is None:
        return ""
    for key in keys:
        try:
            value = tags.get(key)
        except Exception:
            value = None
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        text = str(value).strip()
        if text:
            return text
    return ""


def read_track(path: Path) -> Track:
    """Lê as tags de um arquivo. Em caso de erro devolve uma Track só com o caminho."""
    track = Track(path=path)
    try:
        audio = mutagen.File(path, easy=True)
        if audio is None:
            audio = mutagen.File(path)
    except Exception:
        return track
    if audio is None:
        return track

    tags = getattr(audio, "tags", None)
    # Chaves "fáceis" (Vorbis/EasyID3/EasyMP4/APE) e frames ID3 (WAV/AIFF).
    track.title = _first(tags, "title", "TIT2")
    track.artist = _first(tags, "artist", "TPE1")
    track.album = _first(tags, "album", "TALB")
    track.album_artist = _first(tags, "albumartist", "TPE2")

    info = getattr(audio, "info", None)
    length = getattr(info, "length", 0.0) if info is not None else 0.0
    try:
        track.duration = float(length or 0.0)
    except (TypeError, ValueError):
        track.duration = 0.0
    return track


def find_audio_files(folder: Path) -> list[Path]:
    """Lista recursivamente os arquivos de áudio de uma pasta, em ordem estável."""
    files: list[Path] = []
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        for name in sorted(names):
            if name.startswith("."):
                continue
            if Path(name).suffix.lower() in AUDIO_EXTENSIONS:
                files.append(Path(root) / name)
    return files


def scan_folder(
    folder: Path,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> list[Track]:
    """Varre a pasta (recursivamente) e devolve as faixas encontradas.

    `progress(feitos, total)` é chamado após cada arquivo; `cancelled()` permite
    interromper a varredura (devolve o que já foi lido).
    """
    folder = Path(folder)
    files = find_audio_files(folder)
    total = len(files)
    tracks: list[Track] = []
    for index, file in enumerate(files, start=1):
        if cancelled is not None and cancelled():
            break
        tracks.append(read_track(file))
        if progress is not None:
            progress(index, total)
    return tracks
