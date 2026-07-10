# Changelog

All notable changes to this project will be documented in this file.  
本文档用于记录 LaunchFlow 的主要版本更新与变更内容。

---

## [Unreleased]

### Added / 新增
- 发布版编辑器不再直接禁用导出 EXE，导出时会尝试使用系统可用的 PyInstaller 构建器。
- 用户启动包导出时会自动携带可复制的本地应用启动文件，包括 `.exe`、`.bat`、`.cmd`、`.com`、`.ps1`。
- 新增真实导出 smoke 验证脚本 `tools/validate_export_smoke.py`。
- 新增 spinbox UI 结构合约检查脚本 `tools/check_ui_spinbox_contract.py`。
- 新增编辑器 GUI smoke 验证脚本 `tools/check_editor_gui_smoke.py`。
- 新增发布版闭环 smoke 验证脚本 `tools/validate_release_smoke.py`。
- 新增 GUI 人工验证清单 `docs/gui-smoke-checklist.md`。

### Improved / 优化
- 应用步骤选择器补充 `.cmd` 与 `.ps1` 入口类型。
- 优化应用参数与命令输入区高度，减少右侧属性面板被大文本框撑高的问题。
- 导出前提示本地应用文件会随包携带，并说明外部依赖仍需目标环境提供。
- 修复等待/秒数输入框的 QDoubleSpinBox 样式结构，避免上下按钮视觉位置与点击区域偏移。
- 将用户启动包导出的 PyInstaller spec 输出限制在临时构建目录，避免污染项目根目录或用户当前目录。
- 将编辑器发布版构建的 PyInstaller spec 输出限制在 build 目录。
- 补充 `.lnk`、外部依赖、授权私钥和 `.lic` 发布边界说明。
- 补充 `.gitignore` 对 `.lic`、`.tmp/` 与 GUI smoke 临时目录的排除。

---

## [0.1.0-beta] - 2026-04-05

### Added / 新增
- Initial beta release of LaunchFlow
- 可视化启动流程编辑器
- 支持应用、网页、命令、等待四类步骤
- 支持本地方案保存与加载
- 支持工作台内试运行当前方案
- 支持单文件 EXE 导出
- 支持离线激活测试流程
- 支持自定义标题栏与深浅主题切换

### Improved / 优化
- 优化激活窗口交互流程
- 改进标题栏、图标与弹窗的一致性
- 完善 README、Beta Testing Guide 与 Architecture 文档结构
- 调整工作台布局与部分按钮状态逻辑

### Notes / 说明
- This is a beta release
- 当前版本仍处于测试阶段
- 部分功能与交互细节后续仍可能继续调整
- 开发版与发布版在导出行为上可能存在差异
