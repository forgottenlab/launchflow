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
from copy import deepcopy
from pathlib import Path


ASSET_DIR_NAME = "launchflow_assets"
PACKABLE_APP_SUFFIXES = {".exe", ".bat", ".cmd", ".com", ".ps1"}


EMBEDDED_TEMPLATE = r'''
from __future__ import annotations

import os
import sys
import time
import traceback
import subprocess
from pathlib import Path
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import messagebox
except Exception:
    tk = None
    messagebox = None


EMBEDDED_PLAN = __PLAN_DATA__


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
    logs_dir = get_base_dir() / "logs"
    ensure_dir(logs_dir)
    return logs_dir


def get_log_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return get_logs_dir() / f"runtime_{ts}.log"


LOG_PATH = get_log_path()


def log(message: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\\n")


def show_info(title: str, message: str) -> None:
    try:
        if tk and messagebox:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo(title, message)
            root.destroy()
    except Exception:
        pass


def show_error(title: str, message: str) -> None:
    try:
        if tk and messagebox:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(title, message)
            root.destroy()
    except Exception:
        pass


def run_app_step(step: dict) -> None:
    path = str(step.get("path", "")).strip()
    embedded_asset = str(step.get("_embedded_asset", "")).strip()

    if embedded_asset:
        embedded_path = get_asset_base_dir() / embedded_asset
        if embedded_path.exists():
            path = str(embedded_path)
        else:
            log(f"[失败] 内置启动文件不存在: {embedded_path}")
            return

    if not path:
        log("[失败] 应用路径为空")
        return

    if not os.path.exists(path):
        log(f"[失败] 程序路径不存在: {path}")
        return

    ext = Path(path).suffix.lower()
    if ext == ".lnk":
        os.startfile(path)
        log(f"[成功] 已通过快捷方式启动应用: {step.get('name', '应用')}")
        return

    args = step.get("args", [])
    if not isinstance(args, list):
        args = []

    working_dir = step.get("working_dir") or None
    if embedded_asset and not working_dir:
        working_dir = str(Path(path).parent)
    start_minimized = bool(step.get("start_minimized", False))

    startupinfo = None
    if os.name == "nt" and start_minimized:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 6

    if ext == ".ps1":
        subprocess.Popen(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", path] + list(args),
            cwd=working_dir,
            startupinfo=startupinfo,
        )
        log(f"[成功] 已启动 PowerShell 脚本: {step.get('name', '应用')}")
        return

    subprocess.Popen([path] + list(args), cwd=working_dir, startupinfo=startupinfo)
    log(f"[成功] 已启动应用: {step.get('name', '应用')}")


def run_url_step(step: dict) -> None:
    url = str(step.get("url", "")).strip()
    browser_path = str(step.get("browser_path", "")).strip()

    if not url:
        log("[失败] URL 为空")
        return

    if browser_path:
        if not os.path.exists(browser_path):
            log(f"[失败] 浏览器路径不存在: {browser_path}")
            return
        subprocess.Popen([browser_path, url])
    else:
        os.startfile(url)

    log(f"[成功] 已打开网址: {url}")


def run_command_step(step: dict) -> None:
    command = str(step.get("command", "")).strip()
    shell = str(step.get("shell", "cmd")).lower()
    working_dir = step.get("working_dir") or None
    new_window = bool(step.get("new_window", True))

    if not command:
        log("[失败] 命令为空")
        return

    if os.name == "nt":
        if shell == "powershell":
            if new_window:
                subprocess.Popen(
                    ["powershell", "-NoExit", "-Command", command],
                    cwd=working_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                subprocess.Popen(["powershell", "-Command", command], cwd=working_dir)
        else:
            if new_window:
                subprocess.Popen(
                    ["cmd", "/k", command],
                    cwd=working_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                subprocess.Popen(["cmd", "/c", command], cwd=working_dir)
    else:
        subprocess.Popen(command, cwd=working_dir, shell=True)

    log(f"[成功] 已执行命令: {command}")


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
        show_info("执行完成", f"方案执行完成。\\n\\n日志位置：\\n{LOG_PATH}")

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
            "请查看同目录 logs 文件夹中的日志。"
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
        if not isinstance(step, dict) or step.get("type") != "app":
            continue

        raw_path = str(step.get("path", "")).strip()
        if not raw_path:
            continue

        source_path = Path(raw_path)
        if source_path.suffix.lower() not in PACKABLE_APP_SUFFIXES:
            continue

        if not source_path.is_file():
            continue

        source_path = source_path.resolve()
        asset_name = seen_sources.get(source_path)
        if asset_name is None:
            asset_name = _safe_asset_name(len(seen_sources) + 1, source_path)
            seen_sources[source_path] = asset_name
            assets.append((source_path, asset_name))

        step["_embedded_asset"] = f"{ASSET_DIR_NAME}/{asset_name}"

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

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
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
