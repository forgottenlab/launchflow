# Changelog

All notable changes to this project will be documented in this file.  
本文档用于记录 LaunchFlow 的主要版本更新与变更内容。

---

## [Unreleased]

### Added / 新增
- 新增 stdlib-only `shared/platform` 检测与路径适配边界；`shared/app_paths.py` 保持原有 API、Windows/Dev/`LAUNCHFLOW_DATA_DIR` 行为及无副作用路径计算，并由独立 smoke 证明非 Windows 仅为旧回退兼容而非支持声明。
- 新增跨平台耦合审计、支持矩阵与分阶段适配路线图，并加入带审核基线的 stdlib 静态检查，阻止核心包出现未登记的平台耦合。
- 优化中英文 README 的视觉层级，为主要章节增加一致且克制的图标，并补充有效的更新日志入口。
- 增加首批 4 位测试者致谢，特别感谢 ZTS 和 SYZ 持续测试、错误反馈与改进建议。
- 加强 README 文档合同检查，覆盖致谢、标题样式、真实仓库目录、许可链接、写作注释和虚构许可证声明。
- 新增独立英文项目入口 `README_EN.md`，并将 `README.md` 重写为完整简体中文 Beta 用户文档；两份文档均包含语言切换、快速开始、运行/导出边界、离线许可、安全说明、限制和路线图。
- 新增六张由正式 Qt 窗口与控件生成的功能截图，覆盖深浅工作台、步骤排序、日志控制台、最近方案和导出流程。
- 新增 `tools/generate_readme_screenshots.py` 和 `tools/check_readme_docs_smoke.py`，验证真实控件截图、双语内容、链接、版本区分、公开路径脱敏及占位文案清理。
- 新增 `shared/app_icon.py`，统一源码/frozen ICO 路径、Windows AppUserModelID、QApplication 和顶层窗口图标。
- 新增本地历史方案单击/Enter 载入及保存、放弃、取消三路未保存修改保护。
- 新增自定义拖拽预览、扩展首尾投放区、全宽插入指示器、左侧箭头与最终位置提示。
- 新增 `editor/ui/log_console.py`：SYSTEM、EXECUTION、OUTPUT、SUCCESS、WARNING、ERROR、SEPARATOR 富文本分类和有界显示。
- 日志区新增右侧垂直工具栏及 collapsed/normal/expanded 三态布局。
- 新增 `check_app_icon_smoke.py`、`check_plan_history_single_click_smoke.py` 和 `check_log_presentation_smoke.py`。
- 步骤列表支持 Qt `InternalMove` 拖拽排序，并提供 `Alt+Up` / `Alt+Down` 键盘后备；模型通过单一 `reorder_steps()` 入口移动原对象并按 `step_id` 恢复选择。
- 主要按钮、Command Shell 和步骤列表新增与 QAction 快捷键一致的 tooltip。
- 日志区新增清空显示、复制全部、打开日志目录和本地“反馈问题”诊断预览。
- 新增 `shared/diagnostics.py` 和诊断 smoke，对用户路径、machine/request ID、LFREQ1、signature 与私钥引用进行掩码，不读取 license 内容、不自动上传。
- 新增 `docs/interactive-terminal-design.md`，只记录未来交互式终端设计边界。

### Fixed / 修复
- 拖拽 ghost 移除额外主题色外框，只保留一张紧凑、圆角、半透明的真实步骤卡片；插入线、右侧位置提示、首尾投放区和生命周期清理保持不变。
- 将日志状态与显示/隐藏/恢复入口合并到“运行与输出日志”标题行，移除底部大按钮/状态条；右侧五个工具按钮成为无嵌套外框的最终视觉单元，极小高度仍保留明确恢复入口。
- 统一浅色/深色主题下 LineEdit、TextEdit/PlainTextEdit、ComboBox、DoubleSpinBox/SpinBox 的边框与 focus 状态，修复浅色 Command 文本区与背景融在一起的问题。
- 修复 SpinBox 上下子控件尺寸不一致；移除会导致奇数分配的固定 subcontrol 高度，并在三档 Qt scale factor 下验证同宽同高、箭头居中与点击命中。
- 顶部操作栏改用单一背景、明确垂直内边距和居中布局，方案名称、输入框与四个操作按钮在深浅主题和三档 scale factor 下保持对齐。
- 修复 Qt `InternalMove` 完成后继续访问已被删除的 `QListWidgetItem` 导致 `Internal C++ object already deleted`；拖拽生命周期现在只保留 step ID/MIME，并由统一入口清理 drop、leave、cancel 和结束状态。
- 拖拽源位置不再通过修改 item foreground/background 变灰；ghost card 为 90% 宽、92% 高、86% 透明度的单一卡片，位置提示移至右侧以避免遮挡步骤名称。
- 日志右侧工具栏固定为五项并按实际高度响应式显示；collapsed 时完全隐藏，状态摘要与长文本 tooltip 位于标题行。
- QComboBox/QDoubleSpinBox 改用共享 `FieldThemeTokens` 生成分段控件样式，修复浅色/深色下右侧外框、左分隔线、SpinBox 中线和上下圆角不完整的问题。
- 源码窗口不再使用与发布 ICO 分离的动态主图标；图标缺失只记录可读警告，不阻止启动。
- 修复历史方案双击直载可能覆盖未保存草稿、双击重复载入和方向键误触载入的风险。
- 修复原生细线 drop indicator 在首项/末项附近目标过窄、深浅主题辨识度不足的问题。
- 修复日志顶部文字按钮挤占高度、默认可见行数过少、滚动查看旧输出时被新日志抢回底部的问题。
- 修复右侧步骤草稿未在保存、快捷键保存、试运行、导出和步骤切换前写回模型的问题；Command 文本按原样保留引号、换行、`%` 与中文。
- 试运行和导出新增整方案严格预检、错误步骤自动选择/聚焦和深拷贝 worker 快照；保存仍允许不完整草稿。
- Application 子进程改为 fire-and-forget 且 stdin/stdout/stderr 指向 `DEVNULL`，避免 GUI/Electron 子进程输出污染开发终端；Command 捕获语义不变。

### Tests / 测试
- 新增 `tools/check_step_editor_sync_smoke.py`，覆盖保存/快捷键、试运行快照、选择切换、dirty 状态、全方案阻断和 Application 输出隔离。

### Added / 新增
- 新增 `tools/run_editor_dev.ps1`，以进程级 `LAUNCHFLOW_DATA_DIR` 启动 `%LOCALAPPDATA%\LaunchFlow-Dev` 开发环境，并固定使用 `python -m editor.main`。
- 新增 License Admin `issue-dev`：强制 developer edition、默认 1095 天、明确输出路径、`--force` 覆盖保护和审计记录。
- 新增 `tools/check_dev_mode_smoke.py` 与 `docs/online-auth-design.md`，分别覆盖开发授权隔离和未来 Device Authorization Flow 边界。
- 新增编辑器菜单与快捷键：`Ctrl+S` 保存、`Ctrl+Shift+S` 另存为、`Ctrl+R` 运行、`Ctrl+E` 导出 EXE、`Delete` 删除选中步骤。
- 新增 `LFREQ1` 结构化申请码、复制损坏校验和、唯一 `request_id`、统一客户端版本字段与旧申请码兼容解析。
- 新增作者专用 `tools/license_admin.py`/`license_admin_core.py`，支持 inspect、issue、verify、history、stdin、重复签发拒绝与显式 `--force` 审计。
- 新增 `lflic-1` license schema、客户端版本范围校验及管理员 UI/邮件人工审核边界设计。
- 新增申请码和管理员 CLI smoke；所有签名测试只使用系统 TEMP 下的一次性测试密钥。
- 新增 `shared/app_paths.py`，将可变用户数据统一到 `%LOCALAPPDATA%\LaunchFlow`，并提供测试专用 `LAUNCHFLOW_DATA_DIR` 覆盖。
- 新增 `shared/data_migration.py` 与 `shared/app_logging.py`，提供保守 copy-only 旧数据迁移和有界滚动日志。
- 新增 `tools/check_app_paths_smoke.py`、`tools/check_data_migration_smoke.py`、`tools/validate_release_data_isolation.py`。
- GUI smoke 生成深色/浅色主窗口及 SpinBox/ComboBox 四张离屏截图。
- 新增 `runtime/command_runner.py` 与 `tools/check_command_capture_smoke.py`，覆盖命令参数、输出捕获、错误退出码、中文输出、带空格/中文路径和 Windows 无窗口参数。
- 新增由现有工作台 Logo 造型生成的多尺寸 `assets/launchflow.ico` 及生成工具。
- 发布版编辑器不再直接禁用导出 EXE，导出时会尝试使用系统可用的 PyInstaller 构建器。
- 用户启动包导出时会自动携带可复制的本地应用启动文件，包括 `.exe`、`.bat`、`.cmd`、`.com`、`.ps1`。
- 新增真实导出 smoke 验证脚本 `tools/validate_export_smoke.py`。
- 新增 spinbox UI 结构合约检查脚本 `tools/check_ui_spinbox_contract.py`。
- 新增编辑器 GUI smoke 验证脚本 `tools/check_editor_gui_smoke.py`。
- 新增发布版闭环 smoke 验证脚本 `tools/validate_release_smoke.py`。
- 新增 GUI 人工验证清单 `docs/gui-smoke-checklist.md`。

### Improved / 优化
- 点击“+ 应用 / + 网页 / + 命令 / + 等待”后立即选中新步骤、打开对应属性页并聚焦名称输入框；新命令默认保持空命令、`cmd` 和 1.0 秒延迟。
- Command 失败日志在保留 command、stdout、stderr、returncode 的同时，为 9009、路径不存在和权限不足追加普通用户可理解的中文提示。
- Release smoke 使用隔离的伪造无效签名触发 frozen 客户端验签路径，证明内置公钥可解析且无效签名会被安全拒绝；不生成或读取私钥。
- Command 改为 `Popen(list)`、`stdin=DEVNULL`、双 PIPE 与 `communicate()` 完整等待；`vol C:`、大 stdout/stderr、快速/延迟退出和无残留 cmd 进程已覆盖。
- TrialRunWorker 仅在 `QThread.finished` 后释放引用并重新启用按钮，避免 signal 到达后线程仍未完全退出时被替换。
- 非零 Command 退出码作为正常结果记录 stdout/stderr/returncode，不再被误当作进程启动异常。
- License、plans、settings、logs、cache 与 temp 不再依赖 cwd、源码目录或 EXE 所在目录；用户“另存为”和导出 EXE 目标仍可自选。
- 发布 smoke 以测试 AppData 的 7 个目录实际创建作为启动证据，不再只依赖 PyInstaller 父进程存活。
- frozen license 校验保留现有内置公钥信任链，并可在无内置公钥的配置中回退到 `_MEIPASS/data/public_key.pem`；不生成或替换密钥。
- SpinBox 与 Shell ComboBox 使用真实 Qt subcontrol 几何绘制深浅主题箭头，并补齐 hover、pressed、disabled 和下拉列表状态样式。
- 试运行 Command 步骤改为后台等待并捕获 stdout、stderr、return code；非零退出码不再记录为成功。
- Windows Command 步骤不再创建额外控制台；cmd 与 PowerShell 使用可预测的显式参数，cmd 内部引号不再被 Python 二次转义。
- 导出启动器同步使用无窗口 Command 执行和输出日志，并以原生 `MessageBoxW` 替代不必要的 Tk runtime 依赖。
- 编辑器入口在创建窗口前设置 AppUserModelID 和 QApplication 图标，PyInstaller 发布命令显式设置并携带 ICO。
- Release/Export smoke 仅按本次启动 PID 清理测试进程，并增强图标、Command 与原 plan 不变性验证。
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
