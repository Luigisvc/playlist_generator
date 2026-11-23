"""Diálogo para conectar a uma pasta em servidor remoto (SMB, SFTP, FTP, WebDAV...)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from .remote import ADDRESS_EXAMPLE, RemoteCancelled, RemoteConnection, RemoteError

_SETTINGS_ORG = "PlaylistGenerator"
_SETTINGS_APP = "PlaylistGenerator"


class ConnectWorker(QObject):
    """Conecta ao servidor em outra thread. Perguntas do servidor voltam para a janela."""

    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    question = Signal(str, list)

    def __init__(self, address: str, username: str, password: str, domain: str, anonymous: bool):
        super().__init__()
        self._answer: Optional[int] = None
        self._answered = threading.Event()
        self._connection = RemoteConnection(
            address,
            username=username,
            password=password,
            domain=domain,
            anonymous=anonymous,
            question=self._ask,
        )

    def cancel(self) -> None:
        self._connection.cancel()
        self._answered.set()  # libera uma pergunta pendente

    def answer(self, index: Optional[int]) -> None:
        self._answer = index
        self._answered.set()

    def _ask(self, message: str, choices: list[str]) -> Optional[int]:
        """Chamada na thread de trabalho: pergunta na janela e espera a resposta."""
        self._answer = None
        self._answered.clear()
        self.question.emit(message, choices)
        self._answered.wait()
        return self._answer

    def run(self) -> None:
        try:
            path = self._connection.connect()
        except RemoteCancelled:
            self.cancelled.emit()
        except RemoteError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira mensagem na UI
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(str(path))



class RemoteConnectDialog(QDialog):
    """Pede o endereço/credenciais, conecta e devolve o caminho local da pasta."""

    def __init__(self, title: str = "Conectar a servidor remoto", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 0)
        self._title = title
        self._path: Optional[Path] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[ConnectWorker] = None

        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._address = QLineEdit(str(settings.value("remote/address", "")))
        self._address.setPlaceholderText(f"Ex.: {ADDRESS_EXAMPLE}")
        self._anonymous = QCheckBox("Conexão anônima (sem usuário/senha)")
        self._user = QLineEdit(str(settings.value("remote/user", "")))
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        self._domain = QLineEdit(str(settings.value("remote/domain", "")))
        self._domain.setPlaceholderText("Opcional (SMB)")
        self._browse = QCheckBox("Escolher uma subpasta depois de conectar")
        self._browse.setChecked(True)
        self._anonymous.toggled.connect(self._update_fields)

        form = QFormLayout()
        form.addRow("Endereço:", self._address)
        form.addRow("", self._anonymous)
        form.addRow("Usuário:", self._user)
        form.addRow("Senha:", self._password)
        form.addRow("Domínio:", self._domain)
        form.addRow("", self._browse)

        self._status = QLabel(
            "Protocolos: smb, sftp, ftp, dav, nfs... A senha não é salva. "
            "Também aceita \\\\servidor\\pasta."
        )
        self._status.setWordWrap(True)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._connect_btn = buttons.button(QDialogButtonBox.Ok)
        self._connect_btn.setText("Conectar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._start)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._status)
        layout.addWidget(self._progress)
        layout.addWidget(buttons)
        self._update_fields()

    def selected_path(self) -> Optional[Path]:
        return self._path

    # ------------------------------------------------------------- interface
    def _update_fields(self, *_args) -> None:
        busy = self._thread is not None
        anonymous = self._anonymous.isChecked()
        self._address.setEnabled(not busy)
        self._anonymous.setEnabled(not busy)
        self._browse.setEnabled(not busy)
        for field in (self._user, self._password, self._domain):
            field.setEnabled(not busy and not anonymous)
        self._connect_btn.setEnabled(not busy)
        self._progress.setVisible(busy)

    def _start(self) -> None:
        address = self._address.text().strip()
        if not address:
            QMessageBox.warning(self, "Endereço", f"Informe o endereço, ex.: {ADDRESS_EXAMPLE}")
            return
        thread = QThread()
        worker = ConnectWorker(
            address,
            self._user.text().strip(),
            self._password.text(),
            self._domain.text().strip(),
            self._anonymous.isChecked(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        for signal in (worker.succeeded, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failure)
        worker.cancelled.connect(self._on_cancelled)
        worker.question.connect(self._on_question)
        self._thread, self._worker = thread, worker
        self._status.setText("Conectando...")
        self._update_fields()
        thread.start()

    def _finish_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self._update_fields()

    def _on_question(self, message: str, choices: list) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Confirmação do servidor")
        box.setIcon(QMessageBox.Question)
        box.setText(message or "O servidor pede uma confirmação.")
        buttons = [box.addButton(text, QMessageBox.ActionRole) for text in choices]
        box.exec()
        clicked = box.clickedButton()
        index = buttons.index(clicked) if clicked in buttons else None
        if self._worker is not None:
            self._worker.answer(index)

    def _on_failure(self, message: str) -> None:
        self._finish_thread()
        self._status.setText("Falha ao conectar.")
        QMessageBox.critical(self, "Erro de conexão", message)

    def _on_cancelled(self) -> None:
        self._finish_thread()
        self._status.setText("Conexão cancelada.")

    def _on_success(self, path_text: str) -> None:
        self._finish_thread()
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        settings.setValue("remote/address", self._address.text().strip())
        settings.setValue("remote/user", self._user.text().strip())
        settings.setValue("remote/domain", self._domain.text().strip())

        chosen = path_text
        if self._browse.isChecked():
            chosen = QFileDialog.getExistingDirectory(self, self._title, path_text)
            if not chosen:
                self._status.setText("Conectado. Clique em Conectar para escolher a pasta.")
                return
        self._path = Path(chosen)
        self.accept()

    def reject(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self._finish_thread()
        super().reject()
