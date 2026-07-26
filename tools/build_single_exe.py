"""
build_single_exe.py

单文件 EXE 导出工具模块。

该模块负责：
- 根据当前方案字典动态生成嵌入式启动脚本；
- 调用 PyInstaller 将脚本封装为单文件 exe；
- 将方案数据直接嵌入可执行文件，避免依赖外部 plan.json。

位置：
- tools/build_single_exe.py

相关模块：
- editor.ui.main_window
- shared.models

安全与实现说明：
- 这里的“嵌入”仅用于方案数据打包，不涉及授权私钥等敏感信息；
- 导出脚本中保留日志输出能力，方便用户定位运行失败原因；
- 当前实现会额外导出一个调试脚本，便于排查导出 exe 的运行问题。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path

from shared.platform.applications import get_application_launcher
from shared.platform.process import get_command_backend
from shared.platform.urls import get_url_opener


ASSET_DIR_NAME = "launchflow_assets"
PACKABLE_APP_SUFFIXES = {".exe", ".bat", ".cmd", ".com", ".ps1"}
APPLICATION_LAUNCH_SCHEMA = 1
URL_OPEN_SCHEMA = 1
APPLICATION_ASSET_PREFIX = "__LAUNCHFLOW_ASSET__/"
APPLICATION_ASSET_DIR = "__LAUNCHFLOW_ASSET_DIR__"


@contextmanager
def writable_temporary_directory(prefix: str, parent: Path | None = None):
    """Create a writable temp directory without Python 3.13 TemporaryDirectory ACL issues."""
    base_dir = parent or Path(tempfile.gettempdir())
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{prefix}{os.getpid()}-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


EMBEDDED_TEMPLATE = r'''
from __future__ import annotations

import ctypes
import os
import locale
import sys
import time
import traceback
import subprocess
import uuid
from pathlib import Path
from datetime import datetime


EMBEDDED_PLAN = __PLAN_DATA__
APPLICATION_LAUNCH_SCHEMA = 1
URL_OPEN_SCHEMA = 1
APPLICATION_ASSET_PREFIX = "__LAUNCHFLOW_ASSET__/"
APPLICATION_ASSET_DIR = "__LAUNCHFLOW_ASSET_DIR__"


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


def get_logs_dir() -> Path:
    override = os.environ.get("LAUNCHFLOW_DATA_DIR", "").strip()
    if override and Path(os.path.expandvars(override)).expanduser().is_absolute():
        app_data_dir = Path(os.path.expandvars(override)).expanduser()
    else:
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        app_data_dir = (
            Path(local_app_data) / "LaunchFlow"
            if local_app_data
            else Path.home() / "AppData" / "Local" / "LaunchFlow"
        )
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

    if not path:
        log("[失败] 应用路径为空")
        return

    if not os.path.exists(path):
        if embedded_asset:
            log(f"[失败] 内置启动文件不存在: {path}")
        else:
            log(f"[失败] 程序路径不存在: {path}")
        return

    launch_mode = str(launch.get("launch_mode", ""))
    target_kind = str(launch.get("target_kind", ""))
    if launch_mode == "shell_open":
        os.startfile(path)
        log(f"[成功] 已通过快捷方式启动应用: {step.get('name', '应用')}")
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
    if target_kind == "powershell_script":
        log(f"[成功] 已启动 PowerShell 脚本: {step.get('name', '应用')}")
        return
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

    open_mode = str(launch.get("open_mode", ""))
    if open_mode == "process":
        browser_path = str(launch.get("executable", ""))
        if not os.path.exists(browser_path):
            log(f"[失败] 浏览器路径不存在: {browser_path}")
            return
        command_args = [str(value) for value in launch.get("command_args", [])]
        if not command_args:
            raise ValueError("URL 打开参数无效")
        subprocess.Popen(command_args, **url_process_options(launch))
    elif open_mode == "shell_open":
        os.startfile(url)
    else:
        raise ValueError(f"不支持的 URL 打开模式: {open_mode}")

    log(f"[成功] 已打开网址: {url}")


def run_command_step(step: dict) -> None:
    command = str(step.get("command", "")).strip()
    working_dir = step.get("working_dir") or None
    if not command:
        raise ValueError("命令为空")

    launch = step.get("_command_launch")
    if not isinstance(launch, dict):
        raise ValueError("命令启动合同缺失")
    command_args = list(launch.get("command_args", []))
    process_args = list(launch.get("process_args", []))
    if not command_args or not process_args:
        raise ValueError("命令启动参数无效")

    process_options = {}
    creationflags = int(launch.get("creationflags", 0))
    if creationflags:
        process_options["creationflags"] = creationflags
    if launch.get("use_startupinfo", False):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags = int(launch.get("startupinfo_dw_flags", 0))
        startupinfo.wShowWindow = int(launch.get("startupinfo_show_window", 0))
        process_options["startupinfo"] = startupinfo

    process_env = None
    environment_overrides = launch.get("environment_overrides", {})
    if isinstance(environment_overrides, dict) and environment_overrides:
        process_env = os.environ.copy()
        process_env.update({str(key): str(value) for key, value in environment_overrides.items()})
    try:
        process = subprocess.Popen(
            process_args,
            cwd=working_dir,
            env=process_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            **process_options,
        )
        stdout_bytes, stderr_bytes = process.communicate()
        returncode = process.returncode
    except FileNotFoundError as exc:
        log(f"[错误] 无法启动命令: {exc}")
        log("[退出码] -1")
        log("[失败] 命令执行失败")
        log(f"[提示] {launch.get('not_found_hint')}")
        return
    except PermissionError as exc:
        log(f"[错误] 无法启动命令: {exc}")
        log("[退出码] -1")
        log("[失败] 命令执行失败")
        log(f"[提示] {launch.get('permission_hint')}")
        return
    except OSError as exc:
        log(f"[错误] 无法启动命令: {exc}")
        log("[退出码] -1")
        log("[失败] 命令执行失败")
        winerror = getattr(exc, "winerror", None)
        errno = getattr(exc, "errno", None)
        if winerror in {2, 3, 267} or errno == 2:
            log(f"[提示] {launch.get('not_found_hint')}")
        elif winerror == 5 or errno == 13:
            log(f"[提示] {launch.get('permission_hint')}")
        else:
            log(f"[提示] {launch.get('generic_hint')}")
        return

    preferred = locale.getpreferredencoding(False) or "utf-8"
    fallback_encodings = launch.get("fallback_encodings", [])

    def decode_output(data: bytes) -> str:
        seen = set()
        for encoding in [preferred, *fallback_encodings]:
            normalized = str(encoding).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            try:
                return data.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
        return data.decode(preferred, errors="replace")

    stdout = decode_output(stdout_bytes)
    stderr = decode_output(stderr_bytes)

    log(f"[命令] {command}")
    for line in stdout.rstrip().splitlines():
        log(f"[输出] {line}")
    stderr_label = "[标准错误]" if returncode == 0 else "[错误]"
    for line in stderr.rstrip().splitlines():
        log(f"{stderr_label} {line}")
    log(f"[退出码] {returncode}")

    if returncode != 0:
        log("[失败] 命令执行失败")
        if returncode == 9009:
            log(f"[提示] {launch.get('returncode_9009_hint')}")
        else:
            log(f"[提示] {launch.get('generic_hint')}")
        return

    log("[成功] 命令执行完成")


def run_wait_step(step: dict) -> None:
    seconds = max(0, float(step.get("seconds", 0)))
    log(f"[等待] {seconds} 秒")
    time.sleep(seconds)


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
                log(f"[跳过] 步骤 {index}: 数据无效")
                continue

            if not step.get("enabled", True):
                log(f"[跳过] 步骤 {index}: {step.get('name', '未命名步骤')}（已禁用）")
                continue

            step_type = step.get("type")
            log(f"[执行] 步骤 {index}: {step.get('name', '未命名步骤')} ({step_type})")

            if step_type == "app":
                run_app_step(step)
            elif step_type == "url":
                run_url_step(step)
            elif step_type == "command":
                run_command_step(step)
            elif step_type == "wait":
                run_wait_step(step)
            else:
                log(f"[警告] 未知步骤类型: {step_type}")
                continue

            if step_type != "wait":
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
            "请查看 LaunchFlow 用户数据目录中的启动器日志。"
        )


if __name__ == "__main__":
    main()
'''


def _safe_asset_name(index: int, path: Path) -> str:
    """
    为随包携带的本地启动文件生成稳定、安全的文件名。
    """
    stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in path.stem)
    stem = stem.strip("_") or "app"
    return f"app_{index}_{stem}{path.suffix.lower()}"


def _serialized_command_launch(command: str, shell: str) -> dict:
    """Materialize the shared CommandBackend contract for a standalone launcher."""
    backend = get_command_backend()
    spec = backend.build_launch_spec(command, shell)
    startupinfo = spec.startupinfo
    return {
        "command_args": list(spec.command_args),
        "process_args": list(spec.process_args),
        "environment_overrides": dict(spec.environment_overrides),
        "creationflags": spec.creationflags,
        "use_startupinfo": startupinfo is not None,
        "startupinfo_dw_flags": int(getattr(startupinfo, "dwFlags", 0)),
        "startupinfo_show_window": int(getattr(startupinfo, "wShowWindow", 0)),
        "fallback_encodings": list(spec.fallback_encodings),
        "returncode_9009_hint": backend.explain_failure(9009, None),
        "not_found_hint": backend.explain_failure(-1, "not_found"),
        "permission_hint": backend.explain_failure(-1, "permission_denied"),
        "generic_hint": backend.explain_failure(1, None),
    }


def _serialized_application_launch(
    path: str,
    arguments: list[str],
    working_dir: str,
    start_minimized: bool,
) -> dict:
    """Materialize the shared ApplicationLauncher contract for a standalone launcher."""

    launcher = get_application_launcher(
        path_exists=lambda _path: True,
        path_is_directory=lambda _path: False,
    )
    spec = launcher.build_launch_spec(path, arguments, working_dir, start_minimized)
    return {
        "schema": APPLICATION_LAUNCH_SCHEMA,
        "launch_mode": spec.launch_mode,
        "target_kind": spec.target_kind,
        "executable": spec.executable,
        "command_args": list(spec.command_args),
        "cwd": spec.cwd,
        "creationflags": spec.creationflags,
        "use_startupinfo": spec.use_startupinfo,
        "startupinfo_dw_flags": spec.startupinfo_dw_flags,
        "startupinfo_show_window": spec.startupinfo_show_window,
        "use_stdin_devnull": spec.use_stdin_devnull,
        "use_stdout_devnull": spec.use_stdout_devnull,
        "use_stderr_devnull": spec.use_stderr_devnull,
        "resolved_target": spec.resolved_target,
    }


def _serialized_url_open(url: str, browser_path: str) -> dict:
    """Materialize the shared UrlOpener contract for a standalone launcher."""

    opener = get_url_opener(path_exists=lambda _path: True)
    spec = opener.build_open_spec(url, browser_path)
    return {
        "schema": URL_OPEN_SCHEMA,
        "open_mode": spec.open_mode,
        "url": spec.url,
        "executable": spec.executable,
        "command_args": list(spec.command_args),
        "cwd": spec.cwd,
        "creationflags": spec.creationflags,
        "use_startupinfo": spec.use_startupinfo,
        "startupinfo_dw_flags": spec.startupinfo_dw_flags,
        "startupinfo_show_window": spec.startupinfo_show_window,
        "use_stdin_devnull": spec.use_stdin_devnull,
        "use_stdout_devnull": spec.use_stdout_devnull,
        "use_stderr_devnull": spec.use_stderr_devnull,
    }


def _prepare_embedded_plan_and_assets(plan_dict: dict) -> tuple[dict, list[tuple[Path, str]]]:
    """
    复制一份用于打包的方案数据，并收集可随包携带的本地应用文件。

    原始方案不被修改。当前只自动携带明确存在的本地文件型应用入口，
    例如 exe / bat / cmd / com / ps1。快捷方式和浏览器路径仍按原路径执行，
    避免把系统级或第三方浏览器误打进用户启动包。
    """
    embedded_plan = deepcopy(plan_dict)
    assets: list[tuple[Path, str]] = []
    seen_sources: dict[Path, str] = {}

    steps = embedded_plan.get("steps", [])
    if not isinstance(steps, list):
        return embedded_plan, assets

    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue

        if step.get("type") == "command":
            command = str(step.get("command", "")).strip()
            shell = str(step.get("shell", "cmd")).lower()
            compatible_shell = "powershell" if shell == "powershell" else "cmd"
            step["_command_launch"] = _serialized_command_launch(command, compatible_shell)
            continue

        if step.get("type") == "url":
            url = str(step.get("url", "")).strip()
            browser_path = str(step.get("browser_path", "")).strip()
            step["_url_open"] = _serialized_url_open(url, browser_path)
            continue

        if step.get("type") != "app":
            continue

        raw_path = str(step.get("path", "")).strip()
        source_path = Path(raw_path)
        launch_path = raw_path
        launch_working_dir = str(step.get("working_dir", "") or "")
        if source_path.suffix.lower() in PACKABLE_APP_SUFFIXES and source_path.is_file():
            source_path = source_path.resolve()
            asset_name = seen_sources.get(source_path)
            if asset_name is None:
                asset_name = _safe_asset_name(len(seen_sources) + 1, source_path)
                seen_sources[source_path] = asset_name
                assets.append((source_path, asset_name))

            embedded_asset = f"{ASSET_DIR_NAME}/{asset_name}"
            step["_embedded_asset"] = embedded_asset
            launch_path = f"{APPLICATION_ASSET_PREFIX}{embedded_asset}"
            if not launch_working_dir:
                launch_working_dir = APPLICATION_ASSET_DIR

        arguments = step.get("args", [])
        if not isinstance(arguments, list):
            arguments = []
        step["_application_launch"] = _serialized_application_launch(
            launch_path,
            arguments,
            launch_working_dir,
            bool(step.get("start_minimized", False)),
        )

    return embedded_plan, assets


def _get_pyinstaller_command() -> list[str]:
    """
    获取可用的 PyInstaller 调用命令。

    源码模式优先使用当前 Python 环境；发布版 EXE 模式下不能再通过
    `sys.executable -m PyInstaller` 调用，因此改为寻找系统 PATH 中的
    pyinstaller 或 python。
    """
    if getattr(sys, "frozen", False):
        pyinstaller_exe = shutil.which("pyinstaller")
        if pyinstaller_exe:
            return [pyinstaller_exe]

        python_exe = shutil.which("python")
        if python_exe:
            return [python_exe, "-m", "PyInstaller"]

        py_launcher = shutil.which("py")
        if py_launcher:
            return [py_launcher, "-m", "PyInstaller"]

        raise RuntimeError(
            "发布版导出需要系统 PATH 中存在 pyinstaller，"
            "或存在已安装 PyInstaller 的 python/py 命令。"
        )

    try:
        __import__("PyInstaller")
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    return [sys.executable, "-m", "PyInstaller"]


def build_single_file_exe(plan_dict: dict, output_exe_path: Path) -> Path:
    """
    将方案字典封装为单文件 EXE。

    参数：
    - plan_dict: 当前方案对应的字典数据；
    - output_exe_path: 最终 exe 输出路径。

    返回值：
    - 导出完成后的 exe 路径。

    执行流程：
    1. 确保输出目录存在；
    2. 检查 PyInstaller 是否可用；
    3. 在临时目录中生成嵌入式启动脚本；
    4. 调用 PyInstaller 进行单文件打包；
    5. 将生成结果复制到目标路径。
    """
    output_exe_path.parent.mkdir(parents=True, exist_ok=True)

    pyinstaller_command = _get_pyinstaller_command()

    with writable_temporary_directory("launchflow-build-") as tmp_dir:
        script_path = tmp_dir / "embedded_launcher.py"
        staged_assets_dir = tmp_dir / ASSET_DIR_NAME

        embedded_plan, assets = _prepare_embedded_plan_and_assets(plan_dict)
        if assets:
            staged_assets_dir.mkdir(parents=True, exist_ok=True)
            for source_path, asset_name in assets:
                shutil.copy2(source_path, staged_assets_dir / asset_name)

        # 这里使用 repr 而不是 json.dumps，
        # 是为了直接生成可嵌入 Python 源码的字典字面量，避免字符串转义层级更复杂。
        script_content = EMBEDDED_TEMPLATE.replace(
            "__PLAN_DATA__",
            repr(embedded_plan),
        )
        script_path.write_text(script_content, encoding="utf-8")

        # 同时导出一个调试脚本，便于在 EXE 异常时直接定位嵌入运行逻辑问题。
        debug_script = output_exe_path.parent / f"{output_exe_path.stem}_embedded_debug.py"
        debug_script.write_text(script_content, encoding="utf-8")

        dist_dir = tmp_dir / "dist"
        build_dir = tmp_dir / "build"

        command = [
            *pyinstaller_command,
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            output_exe_path.stem,
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(build_dir),
            "--specpath",
            str(tmp_dir),
        ]

        for _, asset_name in assets:
            staged_asset = staged_assets_dir / asset_name
            command.extend([
                "--add-data",
                f"{staged_asset}{os.pathsep}{ASSET_DIR_NAME}",
            ])

        command.append(str(script_path))

        subprocess.run(command, check=True)

        built_exe = dist_dir / f"{output_exe_path.stem}.exe"
        if not built_exe.exists():
            raise FileNotFoundError(f"未找到生成的 exe: {built_exe}")

        shutil.copy2(built_exe, output_exe_path)
        return output_exe_path
