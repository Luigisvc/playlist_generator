"""Widgets auxiliares da interface: varredura em thread e diálogo de adição de faixas."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .scanner import Track, scan_folder


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    if total <= 0:
        return "--:--"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def track_text(track: Track) -> str:
    artist = track.artist or track.album_artist or "Artista desconhecido"
    return f"{artist} - {track.display_title}  [{format_duration(track.duration)}]"


class ScanWorker(QObject):
    """Varre a pasta em outra thread para não travar a janela."""

    progress = Signal(int, int)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            tracks = scan_folder(
                self._folder,
                progress=lambda done, total: self.progress.emit(done, total),
                cancelled=lambda: self._cancel,
            )
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira mensagem na UI
            self.failed.emit(str(exc))
            return
        self.finished.emit(tracks)


def start_scan(folder: Path) -> tuple[QThread, ScanWorker]:
    thread = QThread()
    worker = ScanWorker(folder)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    return thread, worker


class AddTracksDialog(QDialog):
    """Lista as músicas da pasta com filtro de texto e seleção múltipla."""

    def __init__(self, library: Sequence[Track], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Adicionar faixas à playlist")
        self.resize(640, 480)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filtrar por título, artista ou álbum...")
        self._search.textChanged.connect(self._apply_filter)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for track in library:
            item = QListWidgetItem(track_text(track))
            item.setData(Qt.UserRole, track)
            haystack = f"{track.display_title} {track.artist} {track.album_artist} {track.album}"
            item.setData(Qt.UserRole + 1, haystack.casefold())
            self._list.addItem(item)
        self._list.itemDoubleClicked.connect(lambda _item: self.accept())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{len(library)} músicas na pasta. Selecione uma ou mais:"))
        layout.addWidget(self._search)
        layout.addWidget(self._list)
        layout.addWidget(buttons)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for index in range(self._list.count()):
            item = self._list.item(index)
            item.setHidden(bool(needle) and needle not in item.data(Qt.UserRole + 1))

    def selected_tracks(self) -> list[Track]:
        return [item.data(Qt.UserRole) for item in self._list.selectedItems()]
