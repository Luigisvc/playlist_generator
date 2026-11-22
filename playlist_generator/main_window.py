"""Janela principal do Playlist Generator."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .exporters import (
    FORMATS,
    PATH_ABSOLUTE,
    PATH_RELATIVE,
    ExportError,
    ExportOptions,
    export_playlist,
)
from .generator import generate_playlist
from .scanner import Track
from .widgets import AddTracksDialog, ScanWorker, format_duration, start_scan, track_text


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Playlist Generator")
        self.resize(900, 700)

        self._folder: Path | None = None
        self._library: list[Track] = []
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(self._build_source_group())
        layout.addWidget(self._build_playlist_group(), stretch=1)
        layout.addWidget(self._build_export_group())
        self._update_state()

    # ------------------------------------------------------------------ UI
    def _build_source_group(self) -> QGroupBox:
        box = QGroupBox("1. Pasta de músicas")
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        self._folder_label = QLabel("Nenhuma pasta selecionada")
        self._folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        choose = QPushButton("Selecionar pasta...")
        choose.clicked.connect(self._choose_folder)
        row.addWidget(self._folder_label, stretch=1)
        row.addWidget(choose)
        layout.addLayout(row)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)
        self._status = QLabel("")
        layout.addWidget(self._status)
        return box

    def _build_playlist_group(self) -> QGroupBox:
        box = QGroupBox("2. Playlist")
        layout = QVBoxLayout(box)

        gen_row = QHBoxLayout()
        gen_row.addWidget(QLabel("Número de faixas (0 = todas):"))
        self._count = QSpinBox()
        self._count.setRange(0, 100000)
        self._count.setValue(50)
        gen_row.addWidget(self._count)
        self._generate_btn = QPushButton("Gerar playlist")
        self._generate_btn.clicked.connect(self._generate)
        gen_row.addWidget(self._generate_btn)
        gen_row.addStretch(1)
        layout.addLayout(gen_row)

        body = QHBoxLayout()
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list.setDragDropMode(QAbstractItemView.InternalMove)
        self._list.setDefaultDropAction(Qt.MoveAction)
        self._list.model().rowsMoved.connect(lambda *_: self._update_state())
        body.addWidget(self._list, stretch=1)

        side = QVBoxLayout()
        self._add_btn = QPushButton("Adicionar...")
        self._remove_btn = QPushButton("Remover")
        self._up_btn = QPushButton("Subir")
        self._down_btn = QPushButton("Descer")
        self._clear_btn = QPushButton("Limpar")
        self._add_btn.clicked.connect(self._add_tracks)
        self._remove_btn.clicked.connect(self._remove_selected)
        self._up_btn.clicked.connect(lambda: self._move_selected(-1))
        self._down_btn.clicked.connect(lambda: self._move_selected(1))
        self._clear_btn.clicked.connect(self._clear)
        for button in (self._add_btn, self._remove_btn, self._up_btn, self._down_btn, self._clear_btn):
            side.addWidget(button)
        side.addStretch(1)
        body.addLayout(side)
        layout.addLayout(body, stretch=1)

        self._summary = QLabel("")
        layout.addWidget(self._summary)
        return box

    def _build_export_group(self) -> QGroupBox:
        box = QGroupBox("3. Salvar")
        form = QFormLayout(box)

        self._name = QLineEdit("Minha playlist")
        form.addRow("Nome:", self._name)

        self._format = QComboBox()
        for key, label in FORMATS.items():
            self._format.addItem(f".{key} - {label}", key)
        self._format.currentIndexChanged.connect(self._update_state)
        form.addRow("Formato:", self._format)

        self._path_mode = QComboBox()
        self._path_mode.addItem("Relativo à pasta da playlist (recomendado)", PATH_RELATIVE)
        self._path_mode.addItem("Absoluto", PATH_ABSOLUTE)
        self._path_mode.currentIndexChanged.connect(self._update_state)
        form.addRow("Caminhos:", self._path_mode)

        self._prefix = QLineEdit()
        self._prefix.setPlaceholderText("Opcional: pasta da música no servidor, ex.: /music")
        form.addRow("Prefixo no servidor:", self._prefix)

        self._same_folder = QRadioButton("Na mesma pasta das músicas")
        self._dedicated = QRadioButton("Em uma pasta dedicada:")
        self._same_folder.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self._same_folder)
        group.addButton(self._dedicated)
        self._dedicated.toggled.connect(self._update_state)
        form.addRow("Destino:", self._same_folder)

        dedicated_row = QHBoxLayout()
        dedicated_row.addWidget(self._dedicated)
        self._dest_edit = QLineEdit()
        self._dest_edit.setPlaceholderText("Escolha a pasta de destino")
        self._dest_btn = QPushButton("Escolher...")
        self._dest_btn.clicked.connect(self._choose_dest)
        dedicated_row.addWidget(self._dest_edit, stretch=1)
        dedicated_row.addWidget(self._dest_btn)
        form.addRow("", dedicated_row)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        form.addRow("", self._hint)

        self._save_btn = QPushButton("Salvar playlist")
        self._save_btn.clicked.connect(self._save)
        form.addRow("", self._save_btn)
        return box

    # ------------------------------------------------------- pasta / varredura
    def _choose_folder(self) -> None:
        start = str(self._folder) if self._folder else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Selecione a pasta de músicas", start)
        if not chosen:
            return
        self._folder = Path(chosen)
        self._folder_label.setText(chosen)
        self._library = []
        self._list.clear()
        self._start_scan()

    def _start_scan(self) -> None:
        if self._folder is None:
            return
        self._stop_scan()
        thread, worker = start_scan(self._folder)
        worker.progress.connect(self._on_scan_progress)
        worker.finished.connect(self._on_scan_finished)
        worker.failed.connect(self._on_scan_failed)
        self._thread, self._worker = thread, worker
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
        self._status.setText("Procurando músicas...")
        self._update_state()
        thread.start()

    def _stop_scan(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self._finish_scan_thread()

    def _finish_scan_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    def _on_scan_progress(self, done: int, total: int) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._status.setText(f"Lendo tags: {done}/{total}")

    def _on_scan_finished(self, tracks: list) -> None:
        self._library = tracks
        self._progress.setVisible(False)
        self._status.setText(f"{len(tracks)} músicas encontradas.")
        self._finish_scan_thread()
        if not tracks:
            QMessageBox.information(
                self, "Nenhuma música", "Não encontrei arquivos de áudio nessa pasta."
            )
        self._update_state()

    def _on_scan_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._status.setText("Falha ao ler a pasta.")
        self._finish_scan_thread()
        QMessageBox.critical(self, "Erro", f"Não foi possível ler a pasta:\n{message}")
        self._update_state()

    # ----------------------------------------------------------- playlist
    def _playlist_tracks(self) -> list[Track]:
        return [self._list.item(i).data(Qt.UserRole) for i in range(self._list.count())]

    def _append_track(self, track: Track) -> None:
        item = QListWidgetItem(track_text(track))
        item.setData(Qt.UserRole, track)
        item.setToolTip(str(track.path))
        self._list.addItem(item)

    def _generate(self) -> None:
        if not self._library:
            return
        if self._list.count():
            answer = QMessageBox.question(
                self, "Gerar playlist", "Isso substituirá a playlist atual. Continuar?"
            )
            if answer != QMessageBox.Yes:
                return
        self._list.clear()
        for track in generate_playlist(self._library, self._count.value()):
            self._append_track(track)
        self._update_state()

    def _add_tracks(self) -> None:
        dialog = AddTracksDialog(self._library, self)
        if dialog.exec():
            for track in dialog.selected_tracks():
                self._append_track(track)
            self._update_state()

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))
        self._update_state()

    def _clear(self) -> None:
        self._list.clear()
        self._update_state()

    def _move_selected(self, delta: int) -> None:
        rows = sorted(self._list.row(item) for item in self._list.selectedItems())
        if not rows:
            return
        if delta < 0 and rows[0] == 0:
            return
        if delta > 0 and rows[-1] == self._list.count() - 1:
            return
        for row in rows if delta < 0 else reversed(rows):
            item = self._list.takeItem(row)
            self._list.insertItem(row + delta, item)
            item.setSelected(True)
        self._update_state()


    # ------------------------------------------------------------- salvar
    def _choose_dest(self) -> None:
        start = self._dest_edit.text() or (str(self._folder) if self._folder else str(Path.home()))
        chosen = QFileDialog.getExistingDirectory(self, "Pasta de destino da playlist", start)
        if chosen:
            self._dest_edit.setText(chosen)
            self._dedicated.setChecked(True)
        self._update_state()

    def _destination(self) -> Path | None:
        if self._same_folder.isChecked():
            return self._folder
        text = self._dest_edit.text().strip()
        return Path(text) if text else None

    def _save(self) -> None:
        tracks = self._playlist_tracks()
        dest = self._destination()
        if not tracks or self._folder is None:
            return
        if dest is None:
            QMessageBox.warning(self, "Destino", "Escolha a pasta de destino da playlist.")
            return
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "Nome", "Informe um nome para a playlist.")
            return
        opts = ExportOptions(
            name=name,
            dest_dir=dest,
            music_root=self._folder,
            path_mode=self._path_mode.currentData(),
            server_prefix=self._prefix.text(),
        )
        fmt = self._format.currentData()
        try:
            target = export_playlist(tracks, fmt, opts)
        except ExportError as exc:
            QMessageBox.critical(self, "Erro ao salvar", str(exc))
            return
        QMessageBox.information(self, "Playlist salva", f"Arquivo criado:\n{target}")

    # ----------------------------------------------------- estado da janela
    def _update_state(self, *_args) -> None:
        scanning = self._thread is not None
        has_library = bool(self._library) and not scanning
        count = self._list.count()
        total = sum(track.duration for track in self._playlist_tracks())

        self._generate_btn.setEnabled(has_library)
        self._count.setEnabled(has_library)
        self._add_btn.setEnabled(has_library)
        for button in (self._remove_btn, self._up_btn, self._down_btn, self._clear_btn):
            button.setEnabled(count > 0)
        self._save_btn.setEnabled(count > 0 and not scanning)
        self._summary.setText(f"{count} faixas - duração total {format_duration(total)}")

        dedicated = self._dedicated.isChecked()
        self._dest_edit.setEnabled(dedicated)
        self._dest_btn.setEnabled(dedicated)

        is_nsp = self._format.currentData() == "nsp"
        absolute = self._path_mode.currentData() == PATH_ABSOLUTE
        self._path_mode.setEnabled(not is_nsp)
        self._prefix.setEnabled(absolute and not is_nsp)

        notes = []
        if is_nsp:
            notes.append(
                "NSP é uma smart playlist: usa caminhos relativos à biblioteca, não "
                "garante a ordem das faixas e o Navidrome só lê até 100 KB."
            )
        notes.append(
            "O Navidrome importa playlists (.m3u/.m3u8/.nsp) que estejam dentro da "
            "pasta da biblioteca ou na pasta configurada em PlaylistsPath."
        )
        self._hint.setText(" ".join(notes))

    def closeEvent(self, event) -> None:  # noqa: N802 - assinatura do Qt
        self._stop_scan()
        super().closeEvent(event)

