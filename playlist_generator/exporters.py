"""Exportação da playlist para formatos compatíveis com o Navidrome.

Formatos:
  - m3u / m3u8 : lista de caminhos (UTF-8) com #EXTM3U, #PLAYLIST e #EXTINF.
  - pls        : formato INI (File1=, Title1=, Length1=...).
  - xspf       : XML (locations como URIs).
  - nsp        : smart playlist do Navidrome (JSON) com regras `filepath`.

Observações sobre o Navidrome:
  - Caminhos relativos em M3U são resolvidos a partir da pasta do arquivo da
    playlist; caminhos absolutos precisam existir dentro de uma biblioteca.
  - O .nsp é lido com limite de 100 KB e NÃO preserva a ordem das faixas.
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence
from urllib.parse import quote

from .scanner import Track

FORMATS: dict[str, str] = {
    "m3u8": "M3U8 (UTF-8)",
    "m3u": "M3U",
    "pls": "PLS",
    "xspf": "XSPF",
    "nsp": "NSP (smart playlist do Navidrome)",
}

PATH_RELATIVE = "relative"
PATH_ABSOLUTE = "absolute"

NSP_MAX_BYTES = 100 * 1024  # limite de leitura do Navidrome


class ExportError(Exception):
    """Erro ao exportar a playlist."""


@dataclass
class ExportOptions:
    name: str
    dest_dir: Path
    music_root: Path
    path_mode: str = PATH_RELATIVE
    server_prefix: str = ""  # só usado com caminhos absolutos


def sanitize_filename(name: str) -> str:
    """Remove caracteres inválidos em nomes de arquivo (Windows/Linux)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(".")
    return cleaned or "playlist"


def _one_line(text: str) -> str:
    return re.sub(r"[\r\n]+", " ", text).strip()


def _relative_to_root(track: Track, music_root: Path) -> str:
    """Caminho da faixa relativo à pasta raiz, com '/' como separador."""
    try:
        rel = track.path.relative_to(music_root)
    except ValueError:
        rel = Path(os.path.relpath(track.path, music_root))
    return PurePosixPath(*rel.parts).as_posix()


def entry_path(track: Track, opts: ExportOptions) -> str:
    """Caminho da faixa como será escrito em M3U/PLS."""
    if opts.path_mode == PATH_RELATIVE:
        try:
            rel = os.path.relpath(track.path, opts.dest_dir)
            return rel.replace(os.sep, "/")
        except ValueError:  # Windows: outro drive, não há caminho relativo
            return str(track.path)
    prefix = opts.server_prefix.strip()
    if prefix:
        return prefix.rstrip("/\\") + "/" + _relative_to_root(track, opts.music_root)
    return str(track.path)


def _label(track: Track) -> str:
    title = _one_line(track.display_title)
    artist = _one_line(track.artist or track.album_artist)
    return f"{artist} - {title}" if artist else title


def _seconds(track: Track) -> int:
    return int(round(track.duration)) if track.duration > 0 else -1


def build_m3u(tracks: Sequence[Track], opts: ExportOptions) -> str:
    lines = ["#EXTM3U", f"#PLAYLIST:{_one_line(opts.name)}"]
    for track in tracks:
        lines.append(f"#EXTINF:{_seconds(track)},{_label(track)}")
        lines.append(entry_path(track, opts))
    return "\n".join(lines) + "\n"


def build_pls(tracks: Sequence[Track], opts: ExportOptions) -> str:
    lines = ["[playlist]"]
    for index, track in enumerate(tracks, start=1):
        lines.append(f"File{index}={entry_path(track, opts)}")
        lines.append(f"Title{index}={_label(track)}")
        lines.append(f"Length{index}={_seconds(track)}")
    lines.append(f"NumberOfEntries={len(tracks)}")
    lines.append("Version=2")
    return "\n".join(lines) + "\n"


def _location(track: Track, opts: ExportOptions) -> str:
    """Location do XSPF: URI (relativa ou file://) com percent-encoding."""
    path = entry_path(track, opts)
    is_abs = os.path.isabs(path) or re.match(r"^[A-Za-z]:", path) is not None
    if opts.path_mode == PATH_RELATIVE and not is_abs:
        return quote(path, safe="/")
    normalized = path.replace("\\", "/")
    if not normalized.startswith("/"):
        normalized = "/" + normalized  # C:/... -> /C:/...
    return "file://" + quote(normalized, safe="/:")


def build_xspf(tracks: Sequence[Track], opts: ExportOptions) -> bytes:
    root = ET.Element("playlist", {"version": "1", "xmlns": "http://xspf.org/ns/0/"})
    ET.SubElement(root, "title").text = _one_line(opts.name)
    track_list = ET.SubElement(root, "trackList")
    for track in tracks:
        node = ET.SubElement(track_list, "track")
        ET.SubElement(node, "location").text = _location(track, opts)
        ET.SubElement(node, "title").text = _one_line(track.display_title)
        if track.artist or track.album_artist:
            ET.SubElement(node, "creator").text = _one_line(track.artist or track.album_artist)
        if track.album:
            ET.SubElement(node, "album").text = _one_line(track.album)
        if track.duration > 0:
            ET.SubElement(node, "duration").text = str(int(round(track.duration * 1000)))
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def build_nsp(tracks: Sequence[Track], opts: ExportOptions) -> str:
    """Smart playlist com uma regra `is filepath` por faixa (caminho relativo à biblioteca)."""
    rules = [{"is": {"filepath": _relative_to_root(track, opts.music_root)}} for track in tracks]
    data = {
        "name": _one_line(opts.name),
        "comment": "Gerada por Playlist Generator",
        "any": rules,
    }
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    size = len(text.encode("utf-8"))
    if size > NSP_MAX_BYTES:
        raise ExportError(
            f"A playlist NSP ficaria com {size // 1024} KB e o Navidrome só lê até "
            f"{NSP_MAX_BYTES // 1024} KB. Reduza o número de faixas ou use M3U/M3U8."
        )
    return text


def export_playlist(tracks: Sequence[Track], fmt: str, opts: ExportOptions) -> Path:
    """Grava a playlist em `opts.dest_dir` e devolve o caminho do arquivo criado."""
    if fmt not in FORMATS:
        raise ExportError(f"Formato desconhecido: {fmt}")
    if not tracks:
        raise ExportError("A playlist está vazia.")

    dest_dir = Path(opts.dest_dir)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(f"Não foi possível criar a pasta de destino: {exc}") from exc

    opts = ExportOptions(
        name=opts.name,
        dest_dir=dest_dir,
        music_root=Path(opts.music_root),
        path_mode=opts.path_mode,
        server_prefix=opts.server_prefix,
    )
    target = dest_dir / f"{sanitize_filename(opts.name)}.{fmt}"

    if fmt in ("m3u", "m3u8"):
        payload: bytes = build_m3u(tracks, opts).encode("utf-8")
    elif fmt == "pls":
        payload = build_pls(tracks, opts).encode("utf-8")
    elif fmt == "xspf":
        payload = build_xspf(tracks, opts)
    else:
        payload = build_nsp(tracks, opts).encode("utf-8")

    try:
        target.write_bytes(payload)
    except OSError as exc:
        raise ExportError(f"Não foi possível gravar '{target}': {exc}") from exc
    return target

