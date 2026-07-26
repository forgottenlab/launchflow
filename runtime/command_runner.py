"""Command execution helpers shared by LaunchFlow's source runtime.

Command steps are short-lived tasks: they run synchronously inside the caller's
worker thread, capture both output streams, and never request a separate Windows
console. Application steps intentionally keep their independent launch semantics.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Any

from shared.platform.process import CommandLaunchSpec, get_command_backend


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
    return get_command_backend().explain_failure(result.returncode, result.error_kind)


def build_command_args(command: str, shell: str) -> list[str]:
    """Build a predictable shell invocation without splitting user quoting."""
    return list(get_command_backend().build_launch_spec(command, shell).command_args)


def windows_hidden_process_options() -> dict[str, Any]:
    """Return Windows subprocess options that suppress a console window."""
    spec = get_command_backend().build_launch_spec("", "cmd")
    return _process_options(spec)


def _process_options(spec: CommandLaunchSpec) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if spec.creationflags:
        options["creationflags"] = spec.creationflags
    if spec.startupinfo is not None:
        options["startupinfo"] = spec.startupinfo
    return options


def _decode_output(data: bytes) -> str:
    """Decode redirected Windows output without allowing decode failures."""
    return get_command_backend().decode_output(data)


def execute_command(command: str, shell: str = "cmd", working_dir: str = "") -> CommandResult:
    """Run a command, wait for completion, and capture stdout/stderr/exit code."""
    if not command.strip():
        raise ValueError("命令为空")

    backend = get_command_backend()
    launch_spec = backend.build_launch_spec(command, shell)
    command_args = list(launch_spec.command_args)
    process_args = list(launch_spec.process_args)
    process_env = None
    if launch_spec.environment_overrides:
        process_env = os.environ.copy()
        process_env.update(launch_spec.environment_overrides)
    try:
        process = subprocess.Popen(
            process_args,
            cwd=working_dir or None,
            env=process_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            **_process_options(launch_spec),
        )
        stdout, stderr = process.communicate()
    except FileNotFoundError as exc:
        message = f"未找到命令解释器或工作目录: {exc}"
        error_kind = backend.classify_launch_error(exc)
        return CommandResult(command_args, -1, "", message, message, error_kind)
    except PermissionError as exc:
        message = f"没有权限启动命令: {exc}"
        error_kind = backend.classify_launch_error(exc)
        return CommandResult(command_args, -1, "", message, message, error_kind)
    except OSError as exc:
        message = f"启动命令时发生系统错误: {exc}"
        error_kind = backend.classify_launch_error(exc)
        return CommandResult(command_args, -1, "", message, message, error_kind)

    return CommandResult(
        command_args=command_args,
        returncode=process.returncode,
        stdout=backend.decode_output(stdout),
        stderr=backend.decode_output(stderr),
    )
