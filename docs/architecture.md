# Architecture Overview

本文档用于说明 LaunchFlow 当前版本的模块划分、核心流程与目录职责。

---

## 1. 项目目标

LaunchFlow 的核心目标是：

- 让用户通过图形界面编排启动流程
- 将启动方案保存为结构化数据
- 在本地直接试运行当前方案
- 在需要时导出为独立启动程序
- 通过离线激活机制控制测试版分发

---

## 2. 总体架构

项目当前可以理解为由四层组成：

1. **界面层**
2. **方案与模型层**
3. **运行时执行层**
4. **授权与工具层**

---

## 3. 模块划分

### 3.1 editor/

图形界面与工作台逻辑所在目录。

主要职责：

- 主窗口构建
- 步骤编辑
- 主题切换
- 历史方案管理
- 试运行与导出入口

核心文件示例：

- `editor/main.py`
- `editor/ui/main_window.py`
- `editor/ui/activation_window.py`
- `editor/services/plan_service.py`

---

### 3.2 shared/

通用模型、结构校验、工具函数与统一元信息所在目录。

主要职责：

- 定义方案与步骤对象
- 提供 JSON 读写与目录工具
- 校验方案结构是否合法
- 统一维护应用元信息

核心文件示例：

- `shared/models.py`
- `shared/plan_schema.py`
- `shared/utils.py`
- `shared/app_info.py`

---

### 3.3 runtime/

运行时执行相关模块。

主要职责：

- 顺序执行方案步骤
- 处理应用、网址、命令、等待等具体运行逻辑
- 为调试运行与试运行提供底层执行器

核心文件示例：

- `runtime/launcher_runtime.py`
- `runtime/launcher.py`（调试入口）

说明：

- 当前正式导出以单文件 EXE 为主
- `runtime/launcher.py` 更多用于开发调试
- `runtime/launcher_runtime.py` 目前仍被主工作台试运行逻辑复用

---

### 3.4 licensing/

离线授权相关模块。

主要职责：

- 生成申请码
- 管理本地授权文件
- 验证签名
- 绑定机器码
- 校验授权是否过期

核心文件示例：

- `licensing/hwid.py`
- `licensing/crypto.py`
- `licensing/license_manager.py`
- `licensing/activation_service.py`

---

### 3.5 tools/

开发者工具脚本目录。

主要职责：

- 打包编辑器发布版
- 生成单文件导出 exe
- 生成 RSA 密钥对
- 根据申请码签发 license 文件

核心文件示例：

- `tools/build_editor_release.py`
- `tools/build_single_exe.py`
- `tools/generate_keys.py`
- `tools/license_generator.py`

---

## 4. 核心数据结构

### 4.1 Plan

方案对象，表示一个完整的启动流程。

主要字段：

- `plan_name`
- `version`
- `steps`

---

### 4.2 Step

当前支持四类步骤：

- `AppStep`
- `UrlStep`
- `CommandStep`
- `WaitStep`

公共字段：

- `id`
- `type`
- `name`
- `enabled`
- `delay_after`

---

## 5. 主工作流

### 5.1 编辑流程

1. 用户启动主程序
2. 进入工作台
3. 新建或载入方案
4. 添加不同类型步骤
5. 编辑步骤参数
6. 保存方案到本地 JSON

---

### 5.2 试运行流程

1. 用户点击 **试运行**
2. 主窗口创建后台线程
3. 后台线程调用 `RuntimeExecutor`
4. 执行步骤并回传日志
5. 日志展示在底部控制台区域

---

### 5.3 导出流程

1. 用户点击 **导出 EXE**
2. 当前方案被转换为字典数据
3. 工具脚本生成嵌入式启动脚本
4. 收集可随包携带的本地应用启动文件
5. 使用 PyInstaller 打包
6. 输出独立可执行文件

当前导出方式特点：

- 方案数据直接嵌入 EXE
- 不依赖外部 `plan.json`
- `.exe`、`.bat`、`.cmd`、`.com`、`.ps1` 应用步骤会自动随包携带
- 运行时优先从 PyInstaller 解包目录启动随包文件
- `.lnk` 快捷方式不作为推荐随包资产，因为其目标通常是机器相关绝对路径
- 只携带启动文件本身，不自动携带外部 DLL、配置目录或数据目录
- 发布版编辑器内导出依赖目标机器存在可用的 PyInstaller 构建器
- 便于分发与使用

---

### 5.4 激活流程

1. 程序启动时先检查本地授权
2. 若未授权，则进入激活窗口
3. 用户复制申请码发送给作者
4. 作者本地生成 `.lic` 文件
5. 用户导入授权文件
6. 程序验证签名、机器码和到期时间
7. 校验通过后进入工作台

---

## 6. 路径策略

当前项目采用“只读资源与用户可变数据分离”的路径策略。

- `shared/app_paths.py` 是可变路径的单一来源。
- Windows 默认根目录为 `%LOCALAPPDATA%\LaunchFlow`。
- `config/` 保存现有主题与偏好；`data/` 保存可写模板副本；`licenses/` 保存固定的 `license.lic`；`plans/` 保存方案；`logs/` 保存有界滚动日志；`cache/` 与 `temp/` 保存构建缓存和临时数据。
- 源码与 PyInstaller onefile 使用相同的可变数据根；cwd、`sys.executable` 所在位置和 `_MEIPASS` 都不能成为可变数据根。
- `LAUNCHFLOW_DATA_DIR` 仅用于开发与自动测试隔离，必须是绝对路径。
- 图标、运行时代码、默认模板与内置公钥属于只读资源，可来自源码树或 `_MEIPASS`。私钥永远不属于运行资源。

旧版便携数据迁移由 `shared/data_migration.py` 处理：只检查项目根、EXE 目录或可识别 cwd 等明确位置；只复制新目录中不存在的目标；不覆盖、不删除、不扫描整盘；拒绝 `private/`、`private_key.pem` 和 `generated_licenses/`。迁移 marker 与结果写入 `config/` 和 `logs/migration.log`，失败不会阻止应用继续启动。

导出启动器是自包含代码，无法导入编辑器的 `shared` 包，但遵循同一根目录契约；其日志位于 `%LOCALAPPDATA%\LaunchFlow\logs\launchers/<launcher-name>/`，目标 EXE 位置仍由用户选择。

---

## 7. 设计取舍

### 当前保留的设计

- 自绘标题栏与按钮
- 深浅主题切换
- 离线激活机制
- 单文件 EXE 导出
- 本地 JSON 方案存储

### 当前暂未做复杂化的部分

- 云端账户系统
- 在线授权服务器
- 远程同步
- 插件系统
- 多平台兼容

---

## 8. 技术选择审查

当前建议继续保持 **Python + PySide6 + PyInstaller** 路线。

原因：

- LaunchFlow 的核心是 Windows 本地流程编排、文件路径选择、脚本启动和离线授权；Python 对这些本地自动化场景实现成本低。
- PySide6 已经支撑当前自定义标题栏、主题、表单和工作台布局，继续修补比迁移更低风险。
- PyInstaller 已经能完成编辑器发布和用户启动包导出，真实 smoke 已验证随包资产可以从 `_MEI.../launchflow_assets/` 执行。
- 当前项目规模仍适合轻量桌面架构，不需要引入前后端分离或复杂 IPC。

可选方案对比：

- Electron / Tauri：适合 Web 技术团队和跨平台 UI，但会引入前端构建、IPC、权限和安装体积/运行时复杂度。当前收益不足以抵消迁移成本。
- C# WPF / WinUI：Windows 原生体验强，长期商业化可考虑；但会重写现有 Python 授权、导出和运行时逻辑。
- Python + Qt：继续适合当前阶段，短期重点应放在导出可靠性、路径安全、UI 细节和测试脚本。
- Python + Tkinter：更轻，但 UI 能力和复杂工作台维护性弱于 Qt，不建议迁回。

短期优化优先级：

1. GUI smoke 与手动点击验证。
2. 发布包闭环验证。
3. 导出复杂依赖提示。
4. 方案文件 schema/versioning。
5. 错误日志和用户可读报错。
6. 再考虑自动更新/插件化。

---

## 9. 后续演进方向

后续可继续考虑：

- 关于页 / 版本页
- 更完整的设置面板
- 方案导入导出
- 更丰富的步骤类型
- 更完善的日志查看器
- 更强的导出异常诊断
- 更清晰的开源仓库结构

---

## 10. Beta 命令执行与 Windows 身份

- 源码试运行调用链为 `MainWindow` → `TrialRunWorker(QThread)` → `RuntimeExecutor` → `runtime.command_runner`。Qt 主线程只接收 Signal 日志，不直接等待子进程。
- Command 与 Application 保持不同语义：Command 等待完成并捕获 stdout/stderr/return code；Application 继续按长期 GUI/脚本启动项语义使用 `Popen`。
- Windows Command 使用 `CREATE_NO_WINDOW`、`STARTF_USESHOWWINDOW`、`SW_HIDE`。cmd 前缀为 `cmd.exe /d /s /c`，PowerShell 为无 Profile、NonInteractive 调用。
- 导出启动器是独立嵌入式执行器，不直接导入源码 RuntimeExecutor，但同步执行相同的无窗口与结果判断策略；随包应用资产仍从 `_MEIPASS/launchflow_assets` 解析。
- `editor/main.py` 在创建 QApplication 前设置 `forgottenlab.launchflow.editor`，并从源码 `assets/` 或 frozen `_MEIPASS/assets/` 加载 ICO。
- PyInstaller 构建必须在完整 Conda 激活环境中执行，尤其需让 `Library/bin` 进入 PATH，以便正确收集运行时 DLL。

## 11. Command pipe and license administration boundaries

- UI 试运行链路为 `MainWindow` → `TrialRunWorker(QThread)` → `RuntimeExecutor` → `runtime.command_runner.execute_command`。
- Command 使用参数列表、`shell=False`、`stdin=DEVNULL`、stdout/stderr PIPE 和 `communicate()`；Windows 保留 `CREATE_NO_WINDOW`。含双引号的 cmd 文本使用一次性环境变量恢复引号，避免 Python C-runtime quoting 向 cmd 注入反斜杠。
- `success/failed` 只表示业务结果；按钮重新启用和 worker 引用释放必须等待 `QThread.finished`。
- 非零 return code 是已成功启动并完成的进程结果，保留两路输出后记录失败，但不伪装成启动异常。
- 客户端申请码由 `licensing/request_token.py` 管理；`LFREQ1` 包含非秘密请求元数据和复制损坏校验和，旧申请码保持兼容。
- `licensing/license_schema.py` 同时服务客户端验签和作者工具的 schema/版本边界；旧 license 字段仍由 `LicenseManager` 兼容。
- 作者签发逻辑位于 `tools/license_admin_core.py`，CLI 只是 argparse 薄层。公开编辑器不导入 admin core，未来独立管理员 UI 可直接复用它。
- 邮件服务未来只能创建待审核队列和回复草稿；私钥和本地签名操作不得进入邮件服务，第一阶段禁止无人审核自动签发。

## 12. Beta 编辑器交互约定

- 步骤类型仍固定为 `app`、`url`、`command`、`wait`，新增步骤交互不改变模型或 JSON 保存格式。
- 新步骤追加后由 `MainWindow` 统一刷新列表、选中新行、切换属性页并聚焦名称输入框。
- 工具栏按钮与菜单快捷键连接同一组保存、另存为、试运行、导出和删除槽函数，避免维护重复业务逻辑。
- Command 结果的原始 command、stdout、stderr、returncode 继续保留；`runtime.command_runner.friendly_command_error` 只负责附加用户提示。导出启动器的自包含执行器保持相同日志语义。
- 客户端信任链以 `licensing/crypto.py` 的既有内置公钥为准；若 `data/public_key.pem` 存在，发布构建才将该只读资源加入 `_MEIPASS/data/`，且资源必须与内置公钥匹配。私钥不属于客户端资源。

## 13. 授权运行模式隔离

- 正式模式默认数据根为 `%LOCALAPPDATA%\LaunchFlow`，使用正式用户 license。
- 开发者人工测试由 `tools/run_editor_dev.ps1` 把当前进程的 `LAUNCHFLOW_DATA_DIR` 指向 `%LOCALAPPDATA%\LaunchFlow-Dev`；脚本不修改 User/Machine 环境变量。
- developer license 仍是标准 `lflic-1`，必须通过内置公钥验签、当前机器绑定、有效期和版本范围检查。`edition=developer` 本身不授予旁路能力。
- 自动化测试使用独立临时数据根、临时测试密钥和临时测试 license；GUI component smoke 可直接实例化 `MainWindow` 作为明确的 mock-authorized 路径，但不会创建 license。
- 正式 EXE、源码入口和 `LicenseManager` 都不存在 `--skip-license`，普通环境变量只能改变可写数据目录，不能改变授权结论。
- 未来在线登录的客户端/服务端边界见 `docs/online-auth-design.md`；当前 Beta 不实现服务器。

## 14. 编辑器草稿提交与执行快照

- 右侧属性区维护 `current_step_dirty`，方案维护 `plan_dirty`，`loading_editor` 防止模型回填触发伪 dirty；输入过程中不刷新步骤列表、不写 JSON。
- `MainWindow.commit_current_step_editor()` 是唯一草稿写回入口，“保存此步骤修改”、保存、另存为、步骤切换、新增步骤、试运行和导出复用同一逻辑。
- Command 文本写回时不裁剪内容；空值判断只在执行预检中使用 `strip()`，因此引号、换行、百分号和中文保持原样。
- 保存执行结构校验并允许不完整草稿；试运行/导出在任何步骤开始前执行全方案字段预检，定位第一个错误步骤并聚焦字段。
- 通过预检后对 `Plan` 做 `deepcopy`，`TrialRunWorker` 与 `BuildWorker` 只持有稳定快照。
- Application 与 Command 语义继续分离：Application 的 `Popen` 立即返回并使用 `DEVNULL` 隔离三路标准流；Command 仍使用双 PIPE、`communicate()`、return code 和日志捕获。

## 15. 步骤排序与诊断反馈

- `ReorderableStepList` 保留现有 `QListWidget`，使用 Qt `InternalMove`、原生拖动阈值、插入标记和自动滚动；仅允许单项拖动，多选仍用于批量删除。
- 拖动开始先调用 `commit_current_step_editor()`；模型移动集中于 `MainWindow.reorder_steps(source_index, target_index)`，移动原步骤对象，不改变 ID/类型/参数。
- 排序完成只刷新一次列表，并按 `step_id` 恢复选择和右侧编辑器。保存、运行快照与导出快照自然继承 `current_plan.steps` 新顺序。
- `Alt+Up` / `Alt+Down` 在步骤列表聚焦时调用相同入口；输入控件聚焦时不触发移动。
- `shared/diagnostics.py` 只读取当前 UI 日志或 LaunchFlow 日志文件，不读取 license；输出限制为最近 200 行以内并进行路径与标识符掩码。
- 反馈对话框是本地预览/复制入口，不包含网络上传、邮件或 GitHub 调用。日志目录始终由 `shared.app_paths.get_logs_dir()` 解析。

## 16. 应用身份、历史载入与日志呈现

- `shared/app_icon.py` 是唯一应用图标入口：source 使用项目 `assets/launchflow.ico`，frozen 使用 `sys._MEIPASS/assets/launchflow.ico`；`forgottenlab.launchflow.editor` 在 QApplication 前设置。
- MainWindow 与 ActivationWindow 优先继承 QApplication 全局图标，并通过同一资源解析回退。资源缺失只写 warning，不阻断启动；PyInstaller 继续同时使用 `--icon` 和 `--add-data`。
- 历史列表只把 `itemClicked` 与 Enter 视为载入意图。方向键只改变选择；同路径载入被拒绝，dirty 切换先经过 save/discard/cancel 决策。
- 历史目标先安全解析到临时对象，再决定是否替换 `current_plan`，因此文件缺失或 JSON 损坏不会破坏当前编辑状态，也不改变方案 schema。
- `calculate_drop_target()` 集中处理首项上/下半区与 20px 首尾扩展区；自定义 drag layer 只负责视觉和插入索引，最终仍调用 `reorder_steps()`。
- `LogConsole` 以 `LogKind` 和 `QTextCharFormat` 增量写入 QTextDocument，最多保留 4000 blocks；磁盘 logger 始终保存原始纯文本。
- 日志仅在用户位于底部时自动跟随；用户向上查看时保留位置并显示“有新输出”。collapsed/normal/expanded 只改变 splitter 预设，不改变运行日志或 Command 隐藏终端语义。

## 17. 拖拽生命周期、响应式日志工具栏与分段输入控件

- `ReorderableStepList` 不再跨越 `QDrag.exec()` 保存 `QListWidgetItem` 包装对象。拖拽身份写入自定义 MIME 并由 `step_id` 重新定位当前 item；`clear_drag_visual_state()` 只清理 ID、目标索引、cursor 和 viewport，不访问可能失效的 Qt 对象。
- drop 仍只调用 `MainWindow.reorder_steps()`，因此步骤对象、ID、JSON、试运行与导出顺序契约不变。源位置使用 paint overlay 的强调色虚线，ghost 只渲染一张缩放半透明卡片，不叠加第二层主题描边，也不修改 item foreground/background。
- 日志状态和显示/隐藏/恢复入口集中在 `LogHeader`。右侧工具栏只包含五项操作且自身透明无边框，并根据 layout margins、spacing、button size hint 和实际 drawer height 选择 `full`、`expand` 或 `hidden`；`resizeEvent`、`splitterMoved`、三态切换和主题切换共用同一更新入口。
- `collapsed` 隐藏日志正文、说明与右侧工具栏；`normal` 目标高度约 240px；`expanded` 目标约为 splitter 的 50%，同时保留上方编辑区至少 320px。
- `FieldThemeTokens` 是 LineEdit、TextEdit/PlainTextEdit、ComboBox、DoubleSpinBox/SpinBox 边框、focus 和背景的共享来源，也是分段控件 subcontrol、separator 与箭头颜色来源。多行日志控件不继承字段最小高度，避免压低显式日志高度。
- SpinBox 不固定单个 up/down subcontrol 高度，而给整体控件提供偶数可分内容区，由 Qt 生成相同尺寸命中区；主题绘制只在真实 `SC_SpinBoxUp/Down` 矩形内居中箭头。
- `TopBar` 使用 60px 固定高度、8px 上下 margin 和 `AlignVCenter`；标签显式透明，避免浅色主题出现继承背景块。
