"""Restricted Basic standalone-runner template.

This module holds only the Basic export capability set. The Professional
EMBEDDED_TEMPLATE in tools/build_single_exe.py must remain unchanged.
Shared packaging (temporary directories, asset staging, PyInstaller
invocation) stays in the exporter; this template must not expose
Command, Wait, script-app, or unvalidated shortcut shell-open handlers.
"""

from __future__ import annotations


BASIC_EMBEDDED_TEMPLATE = r'''
from __future__ import annotations

import ctypes
import os
import sys
import time
import traceback
import subprocess
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse


EMBEDDED_PLAN = __PLAN_DATA__
APPLICATION_LAUNCH_SCHEMA = 1
URL_OPEN_SCHEMA = 1
APPLICATION_ASSET_PREFIX = "__LAUNCHFLOW_ASSET__/"
APPLICATION_ASSET_DIR = "__LAUNCHFLOW_ASSET_DIR__"
BASIC_DATA_DIR_NAME = "LaunchFlow-Basic"
PROFESSIONAL_DATA_DIR_NAMES = {"LaunchFlow", "LaunchFlow-Dev"}
BASIC_ALLOWED_STEP_TYPES = {"app", "url"}
BASIC_ALLOWED_URL_SCHEMES = {"http", "https"}


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_asset_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return get_base_dir()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _is_professional_data_root(path: Path) -> bool:
    return path.name in PROFESSIONAL_DATA_DIR_NAMES


def default_basic_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / BASIC_DATA_DIR_NAME
    return Path.home() / "AppData" / "Local" / BASIC_DATA_DIR_NAME


def resolve_basic_data_dir() -> Path:
    override = os.environ.get("LAUNCHFLOW_DATA_DIR", "").strip()
    if override:
        candidate = Path(os.path.expandvars(override)).expanduser()
        if candidate.is_absolute() and not _is_professional_data_root(candidate):
            return candidate
    return default_basic_data_dir()


def get_logs_dir() -> Path:
    app_data_dir = resolve_basic_data_dir()
    launcher_name = Path(sys.executable).stem if getattr(sys, "frozen", False) else "source-launcher"
    logs_dir = app_data_dir / "logs" / "launchers" / launcher_name
    ensure_dir(logs_dir)
    return logs_dir


def get_log_path():
    try:
        logs_dir = get_logs_dir()
        old_logs = sorted(logs_dir.glob("runtime_*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale_log in old_logs[20:]:
            try:
                stale_log.unlink()
            except OSError:
                pass
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return logs_dir / f"runtime_{ts}.log"
    except OSError:
        return None


LOG_PATH = get_log_path()


def log(message: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    if LOG_PATH is None:
        return
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\\n")
    except OSError:
        pass


def show_info(title: str, message: str) -> None:
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)
        except (AttributeError, OSError):
            pass


def show_error(title: str, message: str) -> None:
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
        except (AttributeError, OSError):
            pass


def resolve_application_value(value):
    if value == APPLICATION_ASSET_DIR:
        return str(get_asset_base_dir() / "launchflow_assets")
    if isinstance(value, str) and value.startswith(APPLICATION_ASSET_PREFIX):
        relative_path = value[len(APPLICATION_ASSET_PREFIX):]
        return str(get_asset_base_dir() / Path(relative_path))
    return value


def application_process_options(launch: dict) -> dict:
    options = {}
    if launch.get("use_stdin_devnull", False):
        options["stdin"] = subprocess.DEVNULL
    if launch.get("use_stdout_devnull", False):
        options["stdout"] = subprocess.DEVNULL
    if launch.get("use_stderr_devnull", False):
        options["stderr"] = subprocess.DEVNULL
    creationflags = int(launch.get("creationflags", 0))
    if creationflags:
        options["creationflags"] = creationflags
    if launch.get("use_startupinfo", False):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags = int(launch.get("startupinfo_dw_flags", 0))
        startupinfo.wShowWindow = int(launch.get("startupinfo_show_window", 0))
        options["startupinfo"] = startupinfo
    return options


def run_app_step(step: dict) -> None:
    launch = step.get("_application_launch")
    if not isinstance(launch, dict) or launch.get("schema") != APPLICATION_LAUNCH_SCHEMA:
        raise ValueError("应用启动合同缺失或版本不受支持")

    path = str(resolve_application_value(launch.get("resolved_target", "")))
    embedded_asset = str(step.get("_embedded_asset", "")).strip()
    launch_mode = str(launch.get("launch_mode", ""))
    target_kind = str(launch.get("target_kind", ""))

    if launch_mode != "process":
        raise ValueError("Basic 运行器拒绝未经验证的应用启动方式")
    if target_kind and target_kind != "executable":
        raise ValueError("Basic 运行器只允许启动本地可执行文件")
    if not path.lower().endswith(".exe"):
        raise ValueError("Basic 运行器只允许启动 .exe 应用")

    if not path:
        log("[失败] 应用路径为空")
        return

    if not os.path.exists(path):
        if embedded_asset:
            log(f"[失败] 内置启动文件不存在: {path}")
        else:
            log(f"[失败] 程序路径不存在: {path}")
        return

    command_args = [str(resolve_application_value(value)) for value in launch.get("command_args", [])]
    if not command_args:
        raise ValueError("应用启动参数无效")
    working_dir = resolve_application_value(launch.get("cwd"))
    subprocess.Popen(
        command_args,
        cwd=working_dir,
        **application_process_options(launch),
    )
    log(f"[成功] 已启动应用: {step.get('name', '应用')}")


def url_process_options(launch: dict) -> dict:
    options = {}
    cwd = launch.get("cwd")
    if cwd is not None:
        options["cwd"] = cwd
    if launch.get("use_stdin_devnull", False):
        options["stdin"] = subprocess.DEVNULL
    if launch.get("use_stdout_devnull", False):
        options["stdout"] = subprocess.DEVNULL
    if launch.get("use_stderr_devnull", False):
        options["stderr"] = subprocess.DEVNULL
    creationflags = int(launch.get("creationflags", 0))
    if creationflags:
        options["creationflags"] = creationflags
    if launch.get("use_startupinfo", False):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags = int(launch.get("startupinfo_dw_flags", 0))
        startupinfo.wShowWindow = int(launch.get("startupinfo_show_window", 0))
        options["startupinfo"] = startupinfo
    return options


def run_url_step(step: dict) -> None:
    launch = step.get("_url_open")
    if not isinstance(launch, dict) or launch.get("schema") != URL_OPEN_SCHEMA:
        raise ValueError("URL 打开合同缺失或版本不受支持")

    url = str(launch.get("url", ""))
    if not url:
        log("[失败] URL 为空")
        return

    scheme = str(urlparse(url).scheme or "").strip().lower()
    if scheme not in BASIC_ALLOWED_URL_SCHEMES:
        raise ValueError("Basic 运行器只允许 http/https URL")

    open_mode = str(launch.get("open_mode", ""))
    if open_mode != "shell_open":
        raise ValueError("Basic 运行器只允许通过系统默认浏览器打开 URL")
    os.startfile(url)
    log(f"[成功] 已打开网页: {step.get('name', '网页')}")


def reject_unsupported_step(step: dict, index: int) -> None:
    step_type = step.get("type")
    raise ValueError(f"Basic 运行器拒绝不受支持的步骤 {index}: {step.get('name', '未命名步骤')} ({step_type})")


def main() -> None:
    try:
        plan_name = str(EMBEDDED_PLAN.get("plan_name", "未命名方案"))
        steps = EMBEDDED_PLAN.get("steps", [])

        if not isinstance(steps, list):
            raise ValueError("steps 不是有效列表")

        log("=" * 60)
        log(f"开始执行方案: {plan_name}")
        log(f"日志文件: {LOG_PATH}")
        log("=" * 60)

        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ValueError(f"步骤 {index} 数据无效")

            step_type = step.get("type")
            if step_type not in BASIC_ALLOWED_STEP_TYPES:
                reject_unsupported_step(step, index)

            if not step.get("enabled", True):
                log(f"[跳过] 步骤 {index}: {step.get('name', '未命名步骤')}（已禁用）")
                continue

            log(f"[执行] 步骤 {index}: {step.get('name', '未命名步骤')} ({step_type})")

            if step_type == "app":
                run_app_step(step)
            elif step_type == "url":
                run_url_step(step)
            else:
                reject_unsupported_step(step, index)

            delay_after = float(step.get("delay_after", 0))
            if delay_after > 0:
                log(f"[等待] {delay_after} 秒")
                time.sleep(delay_after)

        log("=" * 60)
        log("方案执行完成")
        log("=" * 60)
        log_location = str(LOG_PATH) if LOG_PATH else "日志目录不可写，本次未保存磁盘日志"
        show_info("执行完成", f"方案执行完成。\\n\\n日志位置：\\n{log_location}")

    except Exception:
        tb = traceback.format_exc()
        try:
            log("[致命错误] 程序运行异常")
            log(tb)
        except Exception:
            pass

        show_error(
            "启动失败",
            "程序运行出现异常。\\n\\n"
            "请查看 LaunchFlow-Basic 用户数据目录中的启动器日志。"
        )


if __name__ == "__main__":
    main()
'''
