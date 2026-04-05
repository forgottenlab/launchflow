"""
models.py

方案与步骤数据模型模块。

该模块负责：
- 定义方案对象与各类步骤对象的数据结构；
- 提供步骤与方案的序列化能力；
- 提供从字典恢复模型对象的解析入口。

位置：
- shared/models.py

相关模块：
- shared.plan_schema
- editor.services.plan_service
- runtime.launcher_runtime

说明：
- 当前模型以 dataclass 形式组织，便于序列化、调试与后续扩展；
- 所有方案读写、试运行与导出都以这里定义的数据结构为基础。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Literal
import uuid


StepType = Literal["app", "url", "command", "wait"]


def generate_step_id() -> str:
    """
    生成步骤唯一标识。

    返回值：
    - 以 step- 开头的短 UUID 字符串。
    """
    return f"step-{uuid.uuid4().hex[:8]}"


@dataclass
class BaseStep:
    """
    步骤基类。

    所有步骤类型共享以下基础字段：
    - id
    - type
    - name
    - enabled
    - delay_after
    """

    id: str = field(default_factory=generate_step_id)
    type: StepType = "app"
    name: str = ""
    enabled: bool = True
    delay_after: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """
        将步骤对象转换为字典。
        """
        return asdict(self)


@dataclass
class AppStep(BaseStep):
    """
    应用启动步骤。
    """

    type: StepType = "app"
    path: str = ""
    args: List[str] = field(default_factory=list)
    working_dir: str = ""
    start_minimized: bool = False


@dataclass
class UrlStep(BaseStep):
    """
    网页打开步骤。
    """

    type: StepType = "url"
    url: str = ""
    browser_path: str = ""


@dataclass
class CommandStep(BaseStep):
    """
    命令执行步骤。
    """

    type: StepType = "command"
    command: str = ""
    shell: str = "cmd"
    working_dir: str = ""
    new_window: bool = True


@dataclass
class WaitStep(BaseStep):
    """
    等待步骤。
    """

    type: StepType = "wait"
    seconds: float = 1.0


@dataclass
class Plan:
    """
    方案对象。

    一个方案由：
    - 方案名称
    - 版本号
    - 步骤列表

    三部分组成。
    """

    plan_name: str = "未命名方案"
    version: str = "1.0.0"
    steps: List[BaseStep] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """
        将方案对象转换为可序列化字典。
        """
        return {
            "plan_name": self.plan_name,
            "version": self.version,
            "steps": [step.to_dict() for step in self.steps],
        }


def step_from_dict(data: Dict[str, Any]) -> BaseStep:
    """
    根据字典数据恢复对应的步骤对象。

    参数：
    - data: 单个步骤字典。

    返回值：
    - 解析后的具体步骤对象。

    异常：
    - ValueError: 当步骤类型不受支持时抛出。
    """
    step_type = data.get("type", "app")

    if step_type == "app":
        return AppStep(**data)
    if step_type == "url":
        return UrlStep(**data)
    if step_type == "command":
        return CommandStep(**data)
    if step_type == "wait":
        return WaitStep(**data)

    raise ValueError(f"不支持的步骤类型: {step_type}")


def plan_from_dict(data: Dict[str, Any]) -> Plan:
    """
    根据字典数据恢复方案对象。

    参数：
    - data: 方案字典。

    返回值：
    - 解析后的 Plan 对象。
    """
    steps = [step_from_dict(item) for item in data.get("steps", [])]
    return Plan(
        plan_name=data.get("plan_name", "未命名方案"),
        version=data.get("version", "1.0.0"),
        steps=steps,
    )