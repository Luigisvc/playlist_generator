import stat
import sys
import textwrap

import pytest

from playlist_generator.remote import (
    RemoteCancelled,
    RemoteConnection,
    RemoteError,
    normalize_address,
)

FAKE_GIO = """\
#!{python}
import os, sys

STATE = {state!r}
LOCAL = {local!r}
MODE = {mode!r}


def out(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def ask(label):
    out(label)
    line = sys.stdin.readline()
    if not line:
        sys.exit(3)
    return line.rstrip("\\n")


args = sys.argv[1:]
if args[0] == "info":
    if os.path.exists(STATE):
        out("name: x\\nuri: " + args[-1] + "\\nlocal path: " + LOCAL + "\\n")
        sys.exit(0)
    sys.stderr.write("gio: " + args[-1] + ": Location is not mounted\\n")
    sys.exit(2)

if args[0] == "mount":
    if MODE == "fail":
        sys.stderr.write("gio: " + args[-1] + ": Failed to mount: no route to host\\n")
        sys.exit(2)
    if MODE == "hang":
        import time
        time.sleep(60)
    if MODE == "cert":
        out("Do you trust this certificate?\\n[1] Yes\\n[2] No\\n")
        if ask("Choice: ") != "1":
            sys.stderr.write("gio: refused\\n")
            sys.exit(2)
    else:
        out("Authentication Required\\nEnter user and password\\n")
        user = ask("User [guest]: ")
        domain = ask("Domain [WORKGROUP]: ")
        password = ask("Password: ")
        out("\\n")
        if (user, domain, password) != ("luiz", "HOME", "segredo"):
            sys.stderr.write("gio: " + args[-1] + ": Failed to mount: Permission denied\\n")
            sys.exit(2)
    open(STATE, "w").close()
    sys.exit(0)
sys.exit(1)
"""


@pytest.fixture
def fake_gio(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("GVFS só existe no Linux")
    local = tmp_path / "gvfs" / "share"
    local.mkdir(parents=True)

    def install(mode="auth"):
        bindir = tmp_path / f"bin-{mode}"
        bindir.mkdir(exist_ok=True)
        script = bindir / "gio"
        script.write_text(
            FAKE_GIO.format(
                python=sys.executable,
                state=str(tmp_path / f"mounted-{mode}"),
                local=str(local),
                mode=mode,
            )
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", str(bindir))
        return local

    return install


def test_normalize_address_variants():
    assert normalize_address("smb://srv/musica") == "smb://srv/musica"
    assert normalize_address("  SFTP://user@host:2222/home/m p3 ") == (
        "sftp://user@host:2222/home/m%20p3"
    )
    assert normalize_address("\\\\srv\\share\\Musicas") == "smb://srv/share/Musicas"
    assert normalize_address("//srv/share") == "smb://srv/share"
    assert normalize_address("smb://srv/Música") == "smb://srv/M%C3%BAsica"


@pytest.mark.parametrize("text", ["", "/home/luiz/Musicas", "http://srv/x", "smb://", "srv"])
def test_normalize_address_rejects_invalid(text):
    with pytest.raises(RemoteError):
        normalize_address(text)


def test_connect_answers_credentials_prompts(fake_gio):
    local = fake_gio("auth")
    conn = RemoteConnection(
        "smb://srv/share", username="luiz", password="segredo", domain="HOME"
    )
    assert conn.connect() == local


def test_connect_wrong_password_is_reported(fake_gio):
    fake_gio("auth")
    conn = RemoteConnection("smb://srv/share", username="luiz", password="errada", domain="HOME")
    with pytest.raises(RemoteError, match="Permission denied"):
        conn.connect()


def test_connect_answers_server_question(fake_gio):
    local = fake_gio("cert")
    asked = []

    def question(message, choices):
        asked.append((message, choices))
        return 0

    conn = RemoteConnection("sftp://srv/share", question=question)
    assert conn.connect() == local
    assert asked == [("Do you trust this certificate?", ["Yes", "No"])]


def test_connect_question_cancelled(fake_gio):
    fake_gio("cert")
    conn = RemoteConnection("sftp://srv/share", question=lambda message, choices: None)
    with pytest.raises(RemoteCancelled):
        conn.connect()


def test_connect_failure_message(fake_gio):
    fake_gio("fail")
    with pytest.raises(RemoteError, match="no route to host"):
        RemoteConnection("smb://srv/share").connect()


def test_connect_timeout_when_server_hangs(fake_gio):
    fake_gio("hang")
    conn = RemoteConnection("smb://srv/share", timeout=1.0)
    with pytest.raises(RemoteError, match="Tempo esgotado"):
        conn.connect()


def test_cancel_stops_pending_connection(fake_gio):
    import threading

    fake_gio("hang")
    conn = RemoteConnection("smb://srv/share", timeout=30.0)
    threading.Timer(0.5, conn.cancel).start()
    with pytest.raises(RemoteCancelled):
        conn.connect()


def test_missing_gio_gives_clear_error(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("GVFS só existe no Linux")
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RemoteError, match="gio"):
        RemoteConnection("smb://srv/share").connect()
