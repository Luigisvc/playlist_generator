"""Conexão com pastas em servidores remotos (SMB, SFTP, FTP, WebDAV, NFS...).

No Linux usa o GVFS (comando `gio mount`) e devolve o caminho local FUSE criado pelo
GVFS (`/run/user/<uid>/gvfs/...`), de modo que o resto do programa continue
trabalhando com caminhos comuns. No Windows só endereços SMB são aceitos (viram UNC).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote, unquote, urlsplit

REMOTE_SCHEMES = frozenset({"smb", "sftp", "ssh", "ftp", "ftps", "dav", "davs", "nfs", "afp"})

ADDRESS_EXAMPLE = "smb://servidor/compartilhamento/Musicas"

# Confirmação pedida pelo servidor: (mensagem, opções) -> índice escolhido (None = cancelar).
QuestionCallback = Callable[[str, "list[str]"], Optional[int]]

# Prompts do `gio mount` (literais, não traduzidos): "User: ", "Password: ", "Domain [X]: "...
_PROMPT_RE = re.compile(rb"(?:\A|\n)(User|Domain|Password|Choice)(?: \[[^\]\n]*\])?: \Z")
_LOCAL_PATH_RE = re.compile(r"^local path:\s*(.+?)\s*$", re.MULTILINE)
_CHOICE_RE = re.compile(r"^\[(\d+)\]\s*(.*)$")


class RemoteError(Exception):
    """Falha ao conectar/montar o servidor remoto (mensagem pronta para o usuário)."""


class RemoteCancelled(RemoteError):
    """O usuário cancelou a conexão."""


def normalize_address(text: str) -> str:
    """Valida e normaliza o endereço digitado, devolvendo uma URI (ex.: smb://srv/share).

    Aceita também `\\\\servidor\\compartilhamento` e `//servidor/compartilhamento` (SMB).
    """
    address = text.strip()
    if address.startswith("\\\\"):
        address = "smb:" + address.replace("\\", "/")
    elif address.startswith("//"):
        address = "smb:" + address
    parts = urlsplit(address)
    scheme = parts.scheme.lower()
    if scheme not in REMOTE_SCHEMES or not parts.netloc:
        raise RemoteError(
            f"Endereço inválido. Use o formato {ADDRESS_EXAMPLE} "
            f"(protocolos: {', '.join(sorted(REMOTE_SCHEMES))})."
        )
    return f"{scheme}://{parts.netloc}{quote(unquote(parts.path), safe='/')}"


def _gio_env() -> dict[str, str]:
    """Ambiente para chamar o `gio` do sistema com mensagens em inglês (fáceis de tratar)."""
    env = dict(os.environ)
    # PyInstaller (onefile) aponta LD_LIBRARY_PATH para as bibliotecas embutidas, o que
    # quebra programas do sistema: restaura o valor original.
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    elif getattr(sys, "frozen", False):
        env.pop("LD_LIBRARY_PATH", None)
    env.pop("LC_ALL", None)  # LC_ALL sobrepõe LC_MESSAGES
    env["LC_MESSAGES"] = "C"
    env["LANGUAGE"] = ""
    return env


def _last_error_line(output: str) -> str:
    lines = [line.strip() for line in output.replace("\r", "").split("\n") if line.strip()]
    for line in reversed(lines):
        if line.startswith("gio:"):
            return line[4:].strip()
    return lines[-1] if lines else "erro desconhecido"



class RemoteConnection:
    """Monta um endereço remoto e devolve o caminho local correspondente.

    `connect()` bloqueia: rode em uma thread. `cancel()` pode ser chamado de outra thread.
    O tempo limite não conta o tempo em que o programa espera o usuário responder
    a uma confirmação do servidor (ex.: certificado desconhecido).
    """

    def __init__(
        self,
        address: str,
        username: str = "",
        password: str = "",
        domain: str = "",
        anonymous: bool = False,
        question: Optional[QuestionCallback] = None,
        timeout: float = 60.0,
    ) -> None:
        self._address = address
        self._username = username
        self._password = password
        self._domain = domain
        self._anonymous = anonymous
        self._question = question
        self._timeout = timeout
        self._cancelled = threading.Event()
        self._timed_out = False
        self._asking = False
        self._last_activity = time.monotonic()
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._kill()

    def _kill(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass

    # ------------------------------------------------------------------ API
    def connect(self) -> Path:
        uri = normalize_address(self._address)
        if sys.platform == "win32":
            return self._connect_windows(uri)

        gio = shutil.which("gio")
        if gio is None:
            raise RemoteError(
                "O comando 'gio' não foi encontrado. Instale o GVFS (pacotes gvfs, "
                "gvfs-backends e gvfs-fuse) para acessar servidores remotos."
            )
        env = _gio_env()

        ok, path, message = self._info(gio, uri, env)
        if not ok:  # ainda não montado (ou erro): tenta montar e consulta de novo
            self._mount(gio, uri, env)
            ok, path, message = self._info(gio, uri, env)
        if not ok:
            raise RemoteError(f"Não foi possível acessar {uri}: {message}")
        if path is None:
            raise RemoteError(
                "O servidor foi montado, mas o GVFS não expôs um caminho local. "
                "Verifique se o pacote gvfs-fuse está instalado e ativo."
            )
        if not path.is_dir():
            raise RemoteError(f"O endereço não aponta para uma pasta acessível: {path}")
        return path

    # -------------------------------------------------------------- Windows
    def _connect_windows(self, uri: str) -> Path:
        parts = urlsplit(uri)
        if parts.scheme != "smb":
            raise RemoteError(
                "No Windows só são aceitos endereços SMB (smb://servidor/compartilhamento "
                "ou \\\\servidor\\compartilhamento)."
            )
        path = Path("\\\\" + (parts.hostname or "") + unquote(parts.path).replace("/", "\\"))
        if not path.is_dir():
            raise RemoteError(
                f"Não foi possível acessar {path}. Verifique o endereço e se o Windows "
                "já tem credenciais salvas para esse servidor."
            )
        return path

    # ------------------------------------------------------------------ gio
    def _info(self, gio: str, uri: str, env: dict[str, str]) -> tuple[bool, Optional[Path], str]:
        """Consulta o local. Devolve (consulta_ok, caminho_local, mensagem_de_erro)."""
        try:
            proc = subprocess.Popen(
                [gio, "info", "-a", "standard::name", uri],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            raise RemoteError(f"Não foi possível executar o gio: {exc}") from exc
        with self._lock:
            self._proc = proc
        try:
            if self.cancelled:
                proc.kill()
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return False, None, "tempo esgotado ao consultar o servidor"
        finally:
            with self._lock:
                self._proc = None
        if self.cancelled:
            raise RemoteCancelled("Conexão cancelada.")
        stdout = out.decode("utf-8", errors="replace")
        stderr = err.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            return False, None, _last_error_line(stderr or stdout)
        match = _LOCAL_PATH_RE.search(stdout)
        return True, (Path(match.group(1)) if match else None), ""

    def _mount(self, gio: str, uri: str, env: dict[str, str]) -> None:
        command = [gio, "mount"]
        if self._anonymous:
            command.append("-a")
        command.append(uri)
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                bufsize=0,
            )
        except OSError as exc:
            raise RemoteError(f"Não foi possível executar o gio: {exc}") from exc

        with self._lock:
            self._proc = proc
        self._timed_out = False
        self._last_activity = time.monotonic()
        done = threading.Event()
        watchdog = threading.Thread(target=self._watch, args=(done,), daemon=True)
        watchdog.start()
        try:
            if self.cancelled:
                proc.kill()
            transcript = self._converse(proc)
            code = proc.wait()
        except BaseException:
            proc.kill()
            raise
        finally:
            done.set()
            with self._lock:
                self._proc = None
            for stream in (proc.stdin, proc.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
            proc.wait()

        if self.cancelled:
            raise RemoteCancelled("Conexão cancelada.")
        if self._timed_out:
            raise RemoteError("Tempo esgotado ao conectar ao servidor.")
        lowered = transcript.lower()
        if code != 0 and "already mounted" not in lowered:
            if "doesn't implement mount" in lowered or "doesn’t implement mount" in lowered:
                raise RemoteError(
                    "O GVFS deste sistema não tem suporte a esse protocolo. Instale o "
                    "gvfs-backends (e o gvfs-fuse) e, se o programa estiver em Flatpak/"
                    "Snap, execute-o fora do sandbox."
                )
            raise RemoteError(f"Falha ao conectar: {_last_error_line(transcript)}")

    def _watch(self, done: threading.Event) -> None:
        """Mata o `gio mount` se ficar `timeout` segundos sem progresso (sem contar perguntas)."""
        while not done.wait(0.5):
            if self._asking:
                self._last_activity = time.monotonic()
            elif time.monotonic() - self._last_activity > self._timeout:
                self._timed_out = True
                self._kill()
                return

    def _converse(self, proc: subprocess.Popen) -> str:
        """Lê a saída do `gio mount` e responde aos prompts. Devolve todo o texto lido."""
        transcript = bytearray()
        pending = bytearray()  # texto desde a última resposta
        asked = {"User": 0, "Password": 0}
        while True:
            byte = proc.stdout.read(1)
            if not byte:
                break
            pending += byte
            if byte != b" ":
                continue
            match = _PROMPT_RE.search(pending)
            if match is None:
                continue
            kind = match.group(1).decode()
            if kind in asked:
                asked[kind] += 1
                if asked[kind] > 1:
                    proc.kill()
                    raise RemoteError("Usuário ou senha recusados pelo servidor.")
            reply = self._reply(kind, pending.decode("utf-8", errors="replace"), proc)
            try:
                proc.stdin.write(reply.encode("utf-8") + b"\n")
                proc.stdin.flush()
            except OSError:
                break
            self._last_activity = time.monotonic()
            transcript += pending
            pending.clear()
        transcript += pending
        return transcript.decode("utf-8", errors="replace")

    def _reply(self, kind: str, text: str, proc: subprocess.Popen) -> str:
        if kind == "User":
            return self._username
        if kind == "Domain":
            return self._domain  # vazio = mantém o valor padrão sugerido pelo gio
        if kind == "Password":
            return self._password
        return self._answer_question(text, proc)

    def _answer_question(self, text: str, proc: subprocess.Popen) -> str:
        message_lines: list[str] = []
        choices: list[str] = []
        for line in text.replace("\r", "").split("\n")[:-1]:  # a última linha é o "Choice: "
            match = _CHOICE_RE.match(line.strip())
            if match:
                choices.append(match.group(2))
            elif line.strip():
                message_lines.append(line.strip())
        if self._question is None or not choices:
            proc.kill()
            raise RemoteError("O servidor pediu uma confirmação que não pôde ser respondida.")
        self._asking = True
        try:
            index = self._question("\n".join(message_lines), choices)
        finally:
            self._asking = False
        if index is None or self.cancelled:
            proc.kill()
            raise RemoteCancelled("Conexão cancelada.")
        return str(index + 1)

