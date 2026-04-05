"""
plan_schema.py

方案结构校验模块。

该模块负责：
- 对方案字典执行基础结构校验；
- 检查步骤数组与步骤字段是否满足最低要求；
- 在方案保存、加载与导出前提供统一校验入口。

位置：
- shared/plan_schema.py

相关模块：
- shared.models
- editor.ui.main_window
- runtime.launcher

说明：
- 当前校验以轻量结构校验为主，不承担复杂业务规则约束；
- 返回值统一为错误文本列表，便于直接展示给用户。
"""

from __future__ import annotations

from typing import Dict, Any, List


SUPPORTED_STEP_TYPES = {"app", "url", "command", "wait"}


def validate_plan_dict(plan_data: Dict[str, Any]) -> List[str]:
    """
    校验方案字典的基础结构是否合法。

    参数：
    - plan_data: 待校验的方案字典。

    返回值：
    - 错误文本列表；
    - 若列表为空，表示当前结构通过校验。

    校验内容：
    1. 根对象是否为字典；
    2. 是否包含 plan_name；
    3. steps 是否为数组；
    4. 每个步骤类型是否合法；
    5. 不同步骤类型是否具备必要字段。
    """
    errors: List[str] = []

    if not isinstance(plan_data, dict):
        return ["方案数据必须是对象"]

    if "plan_name" not in plan_data:
        errors.append("缺少 plan_name")

    steps = plan_data.get("steps")
    if not isinstance(steps, list):
        errors.append("steps 必须是数组")
        return errors

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"第 {index + 1} 个步骤必须是对象")
            continue

        step_type = step.get("type")
        if step_type not in SUPPORTED_STEP_TYPES:
            errors.append(f"第 {index + 1} 个步骤类型无效: {step_type}")
            continue

        if "name" not in step:
            errors.append(f"第 {index + 1} 个步骤缺少 name")

        if step_type == "app" and "path" not in step:
            errors.append(f"第 {index + 1} 个 app 步骤缺少 path")

        if step_type == "url" and "url" not in step:
            errors.append(f"第 {index + 1} 个 url 步骤缺少 url")

        if step_type == "command" and "command" not in step:
            errors.append(f"第 {index + 1} 个 command 步骤缺少 command")

        if step_type == "wait" and "seconds" not in step:
            errors.append(f"第 {index + 1} 个 wait 步骤缺少 seconds")

    return errors