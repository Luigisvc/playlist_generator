import os
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from playlist_generator.main_window import MainWindow  # noqa: E402
from playlist_generator.scanner import read_track  # noqa: E402


def write_wav(path, seconds=1):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 8000 * seconds)


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "Music"
    for artist in ("A", "B", "C"):
        (root / artist).mkdir(parents=True)
        for i in range(3):
            write_wav(root / artist / f"{i}.wav", seconds=2)
    return root


def wait_scan(window, timeout=10000):
    QTest.qWait(50)
    waited = 0
    while window._thread is not None and waited < timeout:
        QTest.qWait(50)
        waited += 50
    assert window._thread is None


def test_read_track_reads_duration_from_wav(music):
    track = read_track(music / "A" / "0.wav")
    assert round(track.duration) == 2
    assert track.display_title == "0"


def test_remote_dialog_returns_connected_path(app, music, monkeypatch):
    from playlist_generator import remote_dialog
    from playlist_generator.remote import RemoteConnection

    monkeypatch.setattr(RemoteConnection, "connect", lambda self: music)
    dialog = remote_dialog.RemoteConnectDialog()
    dialog._browse.setChecked(False)
    dialog._address.setText("smb://servidor/musicas")
    dialog._start()
    waited = 0
    while dialog._thread is not None and waited < 5000:
        QTest.qWait(50)
        waited += 50
    assert dialog.selected_path() == music
    assert dialog.result() == QtWidgets.QDialog.Accepted
    dialog.deleteLater()
    QTest.qWait(10)


def test_remote_folder_button_scans_library(app, music, monkeypatch):
    class FakeDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return 1

        def selected_path(self):
            return music

    monkeypatch.setattr("playlist_generator.main_window.RemoteConnectDialog", FakeDialog)
    window = MainWindow()
    window._choose_remote_folder()
    wait_scan(window)
    assert window._folder == music
    assert len(window._library) == 9
    window.close()
    window.deleteLater()
    QTest.qWait(10)


def test_full_flow(app, music, tmp_path, monkeypatch):
    # Diálogos modais bloqueariam o teste: substitui por stubs que registram a chamada.
    shown = []
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(
            QtWidgets.QMessageBox, name, lambda *args, _n=name, **kw: shown.append((_n, args))
        )
    window = MainWindow()
    window._folder = music
    window._start_scan()
    wait_scan(window)
    assert len(window._library) == 9
    assert window._generate_btn.isEnabled()

    window._count.setValue(6)
    window._generate()
    assert window._list.count() == 6

    window._list.setCurrentRow(0)
    first = window._list.item(0).data(Qt.UserRole)
    window._move_selected(1)
    assert window._list.item(1).data(Qt.UserRole) is first
    window._remove_selected()
    assert window._list.count() == 5

    window._same_folder.setChecked(True)
    window._save()
    assert any(p.suffix == ".m3u8" for p in music.iterdir())

    dest = tmp_path / "Playlists"
    window._dedicated.setChecked(True)
    window._dest_edit.setText(str(dest))
    window._format.setCurrentIndex(window._format.findData("xspf"))
    window._name.setText("Teste")
    window._save()
    assert (dest / "Teste.xspf").exists()
    assert [kind for kind, _ in shown] == ["information", "information"]
    window.close()
    window.deleteLater()
    QTest.qWait(10)  # processa o DeferredDelete antes do QApplication ser destruído
