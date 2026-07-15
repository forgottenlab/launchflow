"""Command execution helpers shared by LaunchFlow's source runtime.

Command steps are short-lived tasks: they run synchronously inside the caller's
worker thread, capture both output streams, and never request a separate Windows
console. Application steps intentionally keep their independent launch semantics.
"""

from __future__ import annotations

import locale
import os
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    """Captured result of a command step."""

    command_args: list[str]
    returncode: int
    stdout: str
    stderr: str
    launch_error: str | None = None
    error_kind: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def friendly_command_error(result: CommandResult) -> str | None:
    """Translate common failures without discarding captured diagnostics."""
    if result.succeeded:
        return None
    if result.returncode == 9009:
        return "未找到可执行命令，请检查程序是否安装或是否加入 PATH。"
    if result.error_kind == "not_found":
        return "找不到目标文件，请检查路径。"
    if result.error_kind == "permission_denied":
        return "没有权限执行该操作。"
    return "命令执行失败，请查看退出码和错误输出。"


def build_command_args(command: str, shell: str) -> list[str]:
    """Build a predictable shell invocation without splitting user quoting."""
    shell_name = shell.strip().lower()
    if os.name == "nt":
        if shell_name == "powershell":
            return [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ]
        return ["cmd.exe", "/d", "/s", "/c", command]

    return ["/bin/sh", "-c", command]


def windows_hidden_process_options() -> dict[str, Any]:
    """Return Windows subprocess options that suppress a console window."""
    if os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


def _decode_output(data: bytes) -> str:
    """Decode redirected Windows output without allowing decode failures."""
    preferred = locale.getpreferredencoding(False) or "utf-8"
    encodings = [preferred, "utf-8"]
    if os.name == "nt":
        encodings.extend(["mbcs", "cp936"])

    seen: set[str] = set()
    for encoding in encodings:
        normalized = encoding.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue

    return data.decode(preferred, errors="replace")


def execute_command(command: str, shell: str = "cmd", working_dir: str = "") -> CommandResult:
    """Run a command, wait for completion, and capture stdout/stderr/exit code."""
    if not command.strip():
        raise ValueError("命令为空")

    command_args = build_command_args(command, shell)
    process_args = command_args
    process_env = None
    if os.name == "nt" and shell.strip().lower() != "powershell" and '"' in command:
        # Python converts Windows argument lists with C-runtime quote escaping,
        # which is not cmd.exe quote escaping. Replace only
        # literal double quotes with a unique environment expansion so Popen
        # still receives a list and cmd reconstructs the original text before
        # executing it. Other user variables such as %TEMP% keep working.
        quote_variable = f"__LAUNCHFLOW_DQ_{uuid.uuid4().hex.upper()}"
        while f"%{quote_variable}%" in command:
            quote_variable = f"__LAUNCHFLOW_DQ_{uuid.uuid4().hex.upper()}"
        process_args = [*command_args[:4], command.replace('"', f"%{quote_variable}%")]
        process_env = os.environ.copy()
        process_env[quote_variable] = '"'
    try:
        process = subprocess.Popen(
            process_args,
            cwd=working_dir or None,
            env=process_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            **windows_hidden_process_options(),
        )
        stdout, stderr = process.communicate()
    except FileNotFoundError as exc:
        message = f"未找到命令解释器或工作目录: {exc}"
        return CommandResult(command_args, -1, "", message, message, "not_found")
    except PermissionError as exc:
        message = f"没有权限启动命令: {exc}"
        return CommandResult(command_args, -1, "", message, message, "permission_denied")
    except OSError as exc:
        message = f"启动命令时发生系统错误: {exc}"
        winerror = getattr(exc, "winerror", None)
        errno = getattr(exc, "errno", None)
        if winerror in {2, 3, 267} or errno == 2:
            error_kind = "not_found"
        elif winerror == 5 or errno == 13:
            error_kind = "permission_denied"
        else:
            error_kind = "system_error"
        return CommandResult(command_args, -1, "", message, message, error_kind)

    return CommandResult(
        command_args=command_args,
        returncode=process.returncode,
        stdout=_decode_output(stdout),
        stderr=_decode_output(stderr),
    )
