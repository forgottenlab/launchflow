"""
launcher_runtime.py

运行时执行器模块。

该模块负责：
- 顺序执行方案中的各类步骤；
- 支持应用启动、网页打开、命令执行与等待步骤；
- 对外提供统一日志输出接口，供调试入口与编辑器试运行共用。

位置：
- runtime/launcher_runtime.py

相关模块：
- shared.models
- editor.ui.main_window
- runtime.launcher

说明：
- 当前模块既服务于 runtime 调试入口，也被主工作台中的试运行功能直接复用；
- 因此在项目收敛阶段建议保留，不应直接删除。
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from shared.models import Plan, AppStep, UrlStep, CommandStep, WaitStep


LogCallback = Optional[Callable[[str], None]]


class RuntimeExecutor:
    """
    运行时方案执行器。

    该类负责遍历方案步骤并按顺序执行，
    同时将执行过程通过回调或标准输出的方式反馈给调用方。

    使用场景：
    - runtime/launcher.py 调试运行；
    - 主工作台中的试运行功能。
    """

    def __init__(self, log_callback: LogCallback = None) -> None:
        """
        初始化执行器。

        参数：
        - log_callback: 可选日志回调函数；若为空则直接输出到控制台。
        """
        self.log_callback = log_callback

    def log(self, message: str) -> None:
        """
        输出一条运行日志。

        参数：
        - message: 日志文本。
        """
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def run_plan(self, plan: Plan) -> None:
        """
        执行完整方案。

        参数：
        - plan: 待执行的 Plan 对象。

        执行流程：
        1. 输出开始日志；
        2. 按顺序遍历所有步骤；
        3. 对禁用步骤执行跳过；
        4. 根据步骤类型分发到对应执行方法；
        5. 处理步骤结束后的 delay_after。
        """
        self.log("=" * 60)
        self.log(f"开始执行方案: {plan.plan_name}")
        self.log("=" * 60)

        for index, step in enumerate(plan.steps, start=1):
            if not step.enabled:
                self.log(f"[跳过] 步骤 {index}: {step.name}（已禁用）")
                continue

            self.log(f"[执行] 步骤 {index}: {step.name} ({step.type})")

            if isinstance(step, AppStep):
                self.run_app_step(step)
            elif isinstance(step, UrlStep):
                self.run_url_step(step)
            elif isinstance(step, CommandStep):
                self.run_command_step(step)
            elif isinstance(step, WaitStep):
                self.run_wait_step(step)
            else:
                self.log(f"[警告] 未知步骤类型: {step.type}")
                continue

            if hasattr(step, "delay_after") and step.type != "wait":
                if step.delay_after > 0:
                    self.log(f"[等待] {step.delay_after} 秒")
                    time.sleep(step.delay_after)

        self.log("=" * 60)
        self.log("方案执行完成")
        self.log("=" * 60)

    def run_app_step(self, step: AppStep) -> None:
        """
        执行应用启动步骤。

        参数：
        - step: AppStep 对象。

        异常：
        - FileNotFoundError: 当程序路径不存在时抛出。
        """
        if not os.path.exists(step.path):
            raise FileNotFoundError(f"程序路径不存在: {step.path}")

        ext = Path(step.path).suffix.lower()

        if ext == ".lnk":
            os.startfile(step.path)
            self.log(f"[成功] 已通过快捷方式启动应用: {step.name}")
            return

        command = [step.path] + list(step.args)

        startupinfo = None
        if os.name == "nt" and step.start_minimized:
            # 仅在 Windows 下处理最小化启动，
            # 避免其他平台无对应 STARTUPINFO 时产生兼容性问题。
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 6

        if ext == ".ps1":
            subprocess.Popen(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", step.path] + list(step.args),
                cwd=step.working_dir or None,
                startupinfo=startupinfo,
            )
            self.log(f"[成功] 已启动 PowerShell 脚本: {step.name}")
            return

        subprocess.Popen(
            command,
            cwd=step.working_dir or None,
            startupinfo=startupinfo,
        )
        self.log(f"[成功] 已启动应用: {step.name}")

    def run_url_step(self, step: UrlStep) -> None:
        """
        执行网页打开步骤。

        参数：
        - step: UrlStep 对象。

        异常：
        - ValueError: 当 URL 为空时抛出；
        - FileNotFoundError: 当指定浏览器路径不存在时抛出。
        """
        if not step.url.strip():
            raise ValueError("URL 为空")

        if step.browser_path:
            if not os.path.exists(step.browser_path):
                raise FileNotFoundError(f"浏览器路径不存在: {step.browser_path}")
            subprocess.Popen([step.browser_path, step.url])
        else:
            os.startfile(step.url)

        self.log(f"[成功] 已打开网址: {step.url}")

    def run_command_step(self, step: CommandStep) -> None:
        """
        执行命令步骤。

        参数：
        - step: CommandStep 对象。

        异常：
        - ValueError: 当命令内容为空时抛出。
        """
        if not step.command.strip():
            raise ValueError("命令为空")

        cwd = step.working_dir or None

        if os.name == "nt":
            if step.shell.lower() == "powershell":
                if step.new_window:
                    subprocess.Popen(
                        ["powershell", "-NoExit", "-Command", step.command],
                        cwd=cwd,
                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                    )
                else:
                    subprocess.Popen(["powershell", "-Command", step.command], cwd=cwd)
            else:
                if step.new_window:
                    subprocess.Popen(
                        ["cmd", "/k", step.command],
                        cwd=cwd,
                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                    )
                else:
                    subprocess.Popen(["cmd", "/c", step.command], cwd=cwd)
        else:
            subprocess.Popen(step.command, cwd=cwd, shell=True)

        self.log(f"[成功] 已执行命令: {step.command}")

    def run_wait_step(self, step: WaitStep) -> None:
        """
        执行等待步骤。

        参数：
        - step: WaitStep 对象。

        说明：
        - seconds 小于 0 时会被修正为 0，避免出现无意义的负等待。
        """
        seconds = max(0, step.seconds)
        self.log(f"[等待] {seconds} 秒")
        time.sleep(seconds)
