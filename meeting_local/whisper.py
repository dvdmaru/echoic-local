"""whisper-server 生命週期：起、等、推論、確實關掉。

關鍵：stdout＋stderr 全部導到檔案。只開管線卻沒人讀 whisper-server 的 stderr，
64 KB 管線塞滿後拿著推論 mutex 的 thread 會卡在 write，整個死鎖。導檔＝永遠不會塞。
"""
from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path

from . import config


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


class WhisperServer:
    def __init__(
        self,
        log_path: Path,
        binary: Path | None = None,
        model: Path | None = None,
        port: int = config.WHISPER_PORT,
        threads: int | None = None,
        language: str = config.WHISPER_LANGUAGE,
        vad: bool = config.WHISPER_VAD,
        vad_model: Path | None = None,
        ready_timeout: float = 240.0,
        max_context: int | None = config.WHISPER_MAX_CONTEXT,
        background: bool = False,
    ):
        # 路徑在建構時才讀 config：UI 同一個程序裡剛下載完模型，config 的值已經更新
        vad_model = vad_model or config.VAD_MODEL
        self.log_path = Path(log_path)
        self.binary = Path(binary or config.WHISPER_SERVER)
        self.model = Path(model or config.WHISPER_MODEL)
        self.port = port
        self.background = background
        self.threads = threads or (config.WHISPER_THREADS_BACKGROUND if background else config.WHISPER_THREADS)
        self.gpu = True  # whisper.cpp 預設用 Metal；純 CPU（-ng）實測慢 7.5 倍，背景模式也不用
        self.language = language
        self.vad = vad and Path(vad_model).exists()
        self.vad_model = Path(vad_model)
        self.ready_timeout = ready_timeout
        # -mc 0：每個 30 秒窗不帶前一窗的文字當上下文。關 VAD 時這是防幻覺迴圈的關鍵（2026-10-05 實測 24 組 → 2 組）。
        self.max_context = max_context
        self.proc: subprocess.Popen | None = None
        self._log = None
        self.pid: int | None = None

    # ---- lifecycle -----------------------------------------------------
    def command(self) -> list[str]:
        cmd = [
            str(self.binary), "-m", str(self.model), "-l", self.language,
            "--host", "127.0.0.1", "--port", str(self.port), "-t", str(self.threads), "-pr",
        ]
        if self.vad:
            cmd += ["--vad", "--vad-model", str(self.vad_model)]
        if self.max_context is not None and self.max_context >= 0:
            cmd += ["-mc", str(self.max_context)]
        if self.background and config.BACKGROUND_NICE:
            # 用 nice 指令包起來，不用 preexec_fn（多執行緒程序裡 fork 後跑 Python 不安全）
            cmd = ["/usr/bin/nice", "-n", str(config.BACKGROUND_NICE), *cmd]
        return cmd

    def start(self) -> None:
        if not self.binary.exists():
            raise FileNotFoundError(f"找不到 whisper-server：{self.binary}")
        if not self.model.exists():
            raise FileNotFoundError(f"找不到模型：{self.model}")
        if port_in_use(self.port):
            raise RuntimeError(
                f"port {self.port} 已被占用（可能有上次殘留的 whisper-server）。"
                f"查：lsof -nP -iTCP:{self.port} -sTCP:LISTEN；或用 MEETING_LOCAL_WHISPER_PORT 換 port"
            )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(self.log_path, "ab", buffering=0)
        self._log.write(f"\n===== whisper-server start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n".encode())
        self._log.write((" ".join(self.command()) + "\n").encode())
        self.proc = subprocess.Popen(
            self.command(),
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            cwd=str(self.binary.parent),
            start_new_session=True,
        )
        self.pid = self.proc.pid
        deadline = time.time() + self.ready_timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"whisper-server 啟動就結束（exit {self.proc.returncode}），看 log：{self.log_path}"
                )
            if port_in_use(self.port):
                return
            time.sleep(0.5)
        self.stop()
        raise TimeoutError(f"whisper-server {self.ready_timeout:.0f} 秒內沒開始監聽，看 log：{self.log_path}")

    def stop(self) -> None:
        proc = self.proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait(timeout=10)
        finally:
            if self._log:
                self._log.write(f"===== whisper-server stop rc={proc.returncode} =====\n".encode())
                self._log.close()
                self._log = None
            self.proc = None

    def is_gone(self) -> bool:
        """程序確實不在了（給驗收用）。"""
        if self.pid is None:
            return True
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        # 還在：可能是 zombie（已 wait 過就不會），保守回 False
        return False

    def __enter__(self) -> "WhisperServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ---- inference -----------------------------------------------------
    def transcribe(self, wav: Path, response_format: str = "srt", temperature: float = 0.0,
                   prompt: str | None = None, timeout: float = 4 * 3600) -> str:
        cmd = [
            "curl", "-sS", "--fail-with-body", "--max-time", str(int(timeout)),
            "-F", f"file=@{wav}",
            "-F", f"temperature={temperature}",
            "-F", f"response_format={response_format}",
            "-F", f"language={self.language}",
        ]
        if prompt:
            cmd += ["-F", f"prompt={prompt}"]
        cmd.append(f"http://127.0.0.1:{self.port}/inference")
        # 讀 bytes 不用 text=True：whisper.cpp 偶爾只吐出一個中文字的部分 byte，嚴格 UTF-8 解碼會整份丟掉。
        proc = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        if proc.returncode != 0:
            body = proc.stdout[:500].decode("utf-8", "replace")
            raise RuntimeError(f"whisper 推論失敗（curl rc={proc.returncode}）：{stderr}\n{body}")
        self.raw_bytes = proc.stdout
        text, self.repaired_chars, self.dropped_bytes = decode_whisper_output(proc.stdout)
        return text


# 前段尾巴的殘缺 lead byte＋SRT 段界（空行、序號、時間軸）＋下一段開頭的 continuation bytes
_SPLIT_CHAR = re.compile(
    rb"([\xc2-\xf4][\x80-\xbf]{0,2})(\r?\n\r?\n\d+\r?\n[^\n]*-->[^\n]*\r?\n)([\x80-\xbf]{1,3})"
)


def _utf8_len(lead: int) -> int:
    return 2 if lead < 0xE0 else 3 if lead < 0xF0 else 4


def decode_whisper_output(raw: bytes) -> tuple[str, int, int]:
    """whisper 輸出 → str。回傳（文字, 接回的字數, 丟掉的殘缺處數）。

    殘缺剛好跨 SRT 段界時接回下一段開頭；其餘殘缺處（10/28 實例：同段內少了 lead／尾 byte）丟掉。
    """
    repaired = 0

    def join(m: re.Match) -> bytes:
        nonlocal repaired
        head, sep, tail = m.group(1), m.group(2), m.group(3)
        need = _utf8_len(head[0])
        if len(head) >= need:  # head 本身完整，不是被切開的字
            return m.group(0)
        take = need - len(head)
        try:
            (head + tail[:take]).decode("utf-8")
        except UnicodeDecodeError:
            return m.group(0)
        repaired += 1
        return sep + head + tail

    fixed = _SPLIT_CHAR.sub(join, raw)
    text = fixed.decode("utf-8", "replace")
    dropped = text.count("�")
    return text.replace("�", ""), repaired, dropped
