"""
plan_service.py

方案数据服务模块。

该模块负责：
- 初始化编辑器运行所需的数据目录与默认配置；
- 维护模板、设置项与方案文件的读写；
- 提供步骤创建、方案加载、方案保存与缓存目录访问能力。

位置：
- editor/services/plan_service.py

相关模块：
- shared.models
- shared.utils
- editor.ui.main_window

说明：
- 当前服务层默认采用便携式目录策略；
- 在开发模式和发布模式下，data / logs 等目录都跟随 project_root 管理。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Any

from shared.models import (
    Plan,
    AppStep,
    UrlStep,
    CommandStep,
    WaitStep,
    plan_from_dict,
)
from shared.utils import (
    read_json,
    write_json,
    ensure_dir,
    list_json_files,
    load_or_default_json,
)


DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "type": "url",
        "name": "打开 GitHub",
        "default_url": "https://github.com/",
        "delay_after": 1.0,
    },
    {
        "type": "command",
        "name": "查看 Python 版本",
        "default_command": "python --version",
        "default_shell": "cmd",
        "delay_after": 1.0,
    },
    {
        "type": "wait",
        "name": "等待",
        "default_seconds": 1.0,
    },
]


class PlanService:
    """
    方案服务对象。

    该类负责统一管理：
    - 本地数据目录；
    - 模板配置与用户设置；
    - 方案文件的保存、读取与删除；
    - 构建缓存目录与日志目录。

    使用场景：
    - 主编辑器启动初始化；
    - 新建步骤、保存方案、加载方案；
    - 获取构建缓存路径与日志路径。
    """

    def __init__(self, project_root: Path) -> None:
        """
        初始化方案服务。

        参数：
        - project_root: 当前项目根目录或发布版 exe 所在目录。

        说明：
        - 这里采用便携模式管理数据目录；
        - 开发时指向项目根目录下的 data；
        - 打包后则指向 exe 同目录下的 data。
        """
        self.project_root = project_root

        # 发布版中 project_root 指向 exe 所在目录，
        # 这样 data / logs / user_plans 都可以随程序目录一起移动与备份。
        self.data_dir = self.project_root / "data"
        self.templates_path = self.data_dir / "app_templates.json"
        self.settings_path = self.data_dir / "settings.json"
        self.user_plans_dir = self.data_dir / "user_plans"
        self.build_cache_dir = self.data_dir / "build_cache"
        self.logs_dir = self.project_root / "logs"

        ensure_dir(self.data_dir)
        ensure_dir(self.user_plans_dir)
        ensure_dir(self.build_cache_dir)
        ensure_dir(self.logs_dir)

        self._ensure_default_templates()
        self._ensure_default_settings()

    def _ensure_default_templates(self) -> None:
        """
        确保模板文件存在。

        若模板文件不存在，则写入一份默认模板集合，
        以保证首次启动时即可创建网页、命令和等待步骤。
        """
        if not self.templates_path.exists():
            write_json(self.templates_path, DEFAULT_TEMPLATES)

    def _ensure_default_settings(self) -> None:
        """
        确保设置文件存在且关键字段有效。

        当前主要保证：
        - settings.json 存在；
        - plans_dir 字段不为空；
        - 目标方案目录已创建。
        """
        settings = load_or_default_json(
            self.settings_path,
            {
                "plans_dir": str(self.user_plans_dir),
            },
        )

        raw = str(settings.get("plans_dir", "")).strip()
        if not raw:
            settings["plans_dir"] = str(self.user_plans_dir)

        write_json(self.settings_path, settings)
        ensure_dir(Path(settings["plans_dir"]))

    def load_templates(self) -> List[Dict[str, Any]]:
        """
        加载步骤模板列表。

        返回值：
        - 模板字典列表。

        边界行为：
        - 若模板文件不存在，则直接返回内置默认模板。
        """
        if not self.templates_path.exists():
            return DEFAULT_TEMPLATES
        return read_json(self.templates_path)

    def load_settings(self) -> Dict[str, Any]:
        """
        加载编辑器设置。

        返回值：
        - 设置字典。

        说明：
        - 如果 settings.json 缺失或 plans_dir 为空，
          会自动回退到默认方案目录。
        """
        settings = load_or_default_json(
            self.settings_path,
            {"plans_dir": str(self.user_plans_dir)},
        )

        raw = str(settings.get("plans_dir", "")).strip()
        if not raw:
            settings["plans_dir"] = str(self.user_plans_dir)

        return settings

    def save_settings(self, settings: Dict[str, Any]) -> None:
        """
        保存编辑器设置。

        参数：
        - settings: 要写入的设置字典。

        说明：
        - 为避免写入空方案目录，这里会再次兜底校正 plans_dir。
        """
        raw = str(settings.get("plans_dir", "")).strip()
        if not raw:
            settings["plans_dir"] = str(self.user_plans_dir)
        write_json(self.settings_path, settings)

    def get_plans_dir(self) -> Path:
        """
        获取当前方案目录。

        返回值：
        - 用户方案目录路径。

        说明：
        - 若 settings 中的 plans_dir 为空，则回退为默认 user_plans 目录。
        """
        settings = self.load_settings()
        raw = str(settings.get("plans_dir", "")).strip()
        plans_dir = Path(raw) if raw else self.user_plans_dir
        ensure_dir(plans_dir)
        return plans_dir

    def set_plans_dir(self, plans_dir: Path) -> None:
        """
        更新用户方案目录。

        参数：
        - plans_dir: 新的方案目录路径。
        """
        ensure_dir(plans_dir)
        settings = self.load_settings()
        settings["plans_dir"] = str(plans_dir)
        self.save_settings(settings)

    def list_plan_files(self) -> List[Path]:
        """
        列出当前方案目录下的所有方案文件。

        返回值：
        - 按 JSON 文件形式存在的方案路径列表。
        """
        plans_dir = self.get_plans_dir()
        ensure_dir(plans_dir)
        return list_json_files(plans_dir)

    def create_step_from_template(self, template: Dict[str, Any]):
        """
        根据模板创建步骤实例。

        参数：
        - template: 模板字典，至少需要包含 type 字段。

        返回值：
        - AppStep / UrlStep / CommandStep / WaitStep 之外的三种模板步骤实例。

        异常：
        - ValueError: 当模板类型不受支持时抛出。
        """
        step_type = template.get("type")

        if step_type == "url":
            return UrlStep(
                name=template.get("name", "打开网址"),
                url=template.get("default_url", ""),
                delay_after=template.get("delay_after", 1.0),
            )

        if step_type == "command":
            return CommandStep(
                name=template.get("name", "执行命令"),
                command=template.get("default_command", ""),
                shell=template.get("default_shell", "cmd"),
                delay_after=template.get("delay_after", 1.0),
            )

        if step_type == "wait":
            return WaitStep(
                name=template.get("name", "等待"),
                seconds=template.get("default_seconds", 1.0),
                delay_after=0.0,
            )

        raise ValueError(f"不支持的模板类型: {step_type}")

    def create_app_step(self, app_name: str, app_path: str) -> AppStep:
        """
        创建应用步骤。

        参数：
        - app_name: 应用显示名称；
        - app_path: 应用程序或快捷方式路径。

        返回值：
        - AppStep 实例。
        """
        return AppStep(
            name=app_name or "新应用",
            path=app_path,
            args=[],
            working_dir="",
            delay_after=1.0,
        )

    def save_plan(self, plan: Plan, file_path: Path) -> None:
        """
        保存方案到指定文件。

        参数：
        - plan: 当前方案对象；
        - file_path: 目标文件路径。
        """
        write_json(file_path, plan.to_dict())

    def load_plan(self, file_path: Path) -> Plan:
        """
        从指定文件加载方案对象。

        参数：
        - file_path: 方案文件路径。

        返回值：
        - Plan 实例。
        """
        data = read_json(file_path)
        return plan_from_dict(data)

    def delete_plan(self, file_path: Path) -> None:
        """
        删除指定方案文件。

        参数：
        - file_path: 方案文件路径。
        """
        if file_path.exists():
            file_path.unlink()

    def get_build_cache_dir(self) -> Path:
        """
        获取构建缓存目录。

        返回值：
        - 构建缓存目录路径。
        """
        ensure_dir(self.build_cache_dir)
        return self.build_cache_dir

    def get_cached_exe_path(self, plan_name: str) -> Path:
        """
        获取方案对应的缓存 exe 路径。

        参数：
        - plan_name: 方案名称。

        返回值：
        - 该方案缓存产物的目标路径。
        """
        ensure_dir(self.build_cache_dir)
        return self.build_cache_dir / f"{plan_name}.exe"

    def clear_cached_exe(self, plan_name: str) -> None:
        """
        删除指定方案的缓存 exe。

        参数：
        - plan_name: 方案名称。

        说明：
        - 缓存文件删除失败时保持静默，
          以避免清理阶段影响主流程。
        """
        path = self.get_cached_exe_path(plan_name)
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass

    def get_logs_dir(self) -> Path:
        """
        获取日志目录。

        返回值：
        - 日志目录路径。
        """
        ensure_dir(self.logs_dir)
        return self.logs_dir