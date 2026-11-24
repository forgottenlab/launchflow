# LaunchFlow 双版本架构 — Phase 0 合同冻结

- 状态：Phase 0 合同已冻结（尚未实施生产行为）
- 日期：2026-11-23（Asia/Shanghai）
- 范围：仓库检查、合成夹具、合同测试与验收标准文档
- 明确不在范围内：Basic / Professional 启动入口、GUI 改造、能力注册表接入生产、运行时执行器改造、生产导出器改造、许可/签名/HWID/请求或许可证格式变更、方案 schema 增加 edition 字段、调用 PyInstaller、构建或运行导出 EXE、修改发布标签

本文只冻结后续实现必须遵守的验收标准，并记录当前实现的源码级事实。下文使用以下四类标记，避免把尚未实现的功能写成现状：

| 标记 | 含义 |
| --- | --- |
| 已确认的现有行为 | 可从当前源码直接证明的行为 |
| 新冻结的产品要求 | Phase 0 决定的验收标准，尚待后续阶段实现 |
| 建议的未来架构 | 实现路径建议，不是已完成工作 |
| 未决问题 | 仍需产品或技术决策，不能从现有实现单独推出 |

当前产品支持范围仍是 Windows x86_64 Beta。不得将本文理解为已提供稳定版或跨平台生产支持。macOS arm64 CI 实验不在本阶段范围内。最近公开发布检查点 `v0.1.0-beta.2` 不得在本阶段被修改。

---

## 1. 已确认的现有架构

### 1.1 工作流执行

现有方案模型定义于 `shared/models.py`：

- `Plan` 字段为 `plan_name`、`version`、`steps`，没有 edition 字段。
- 步骤类型由 `StepType = Literal["app", "url", "command", "wait"]` 固定。
- 公共步骤字段：`id`、`type`、`name`、`enabled`、`delay_after`（默认 `1.0`）。
- `AppStep` 另有 `path`、`args`、`working_dir`、`start_minimized`。
- `UrlStep` 另有 `url`、`browser_path`。
- `CommandStep` 另有 `command`、`shell`（默认 `"cmd"`）、`working_dir`、`new_window`。
- `WaitStep` 另有 `seconds`。
- `plan_from_dict()` / `step_from_dict()` 按 `type` 分发，不执行版本能力校验。

`shared/plan_schema.py` 中的 `validate_plan_dict()` 只做轻量结构校验（根对象、`plan_name`、`steps` 数组、类型与必要字段）。它接受全部四种步骤，不拒绝自定义参数、工作目录、自定义浏览器、非 1 秒延迟、未知字段或禁用步骤。

编辑器加载与保存：

- `editor/services/plan_service.py` 的 `PlanService.load_plan()` 读取 JSON 后直接调用 `plan_from_dict()`，没有版本能力校验。
- `PlanService.save_plan()` 只序列化 `Plan.to_dict()`。
- `MainWindow._save_current_plan()` / `_on_save_plan_as()` 在保存前调用 `validate_plan_dict()`。
- 历史方案通过 `MainWindow._load_history_plan_item()` 调用 `PlanService.load_plan()` 载入。当前未发现独立的“从任意路径导入方案”菜单；历史列表是主要的 JSON 载入入口。合同仍然要求未来所有入口（含直接模型/执行器/导出器调用）遵守同一套校验。
- 默认模板 `PlanService.DEFAULT_TEMPLATES` 包含 URL、Command 和 Wait 模板。

执行路径：

- 试运行：`MainWindow._on_trial_run()` → `_prepare_plan_for_execution()` → `TrialRunWorker` → `runtime.launcher_runtime.RuntimeExecutor.run_plan()`。
- `RuntimeExecutor.run_plan()` 按顺序遍历步骤；`enabled=False` 的步骤被跳过；然后按类型分发到 `run_app_step` / `run_url_step` / `run_command_step` / `run_wait_step`；非 wait 步骤在成功分发后按 `delay_after` 睡眠。
- 当前执行器没有版本能力边界，也没有许可证检查。

应用与 URL 启动：

- `shared/platform/applications.py` 中 `WindowsApplicationLauncher.classify_target()` 按后缀分类：`.exe`、`.com`、`.bat`、`.cmd`、`.ps1`、`.lnk`、无扩展名、其他。
- `.lnk` 被分类为 `target_kind="shortcut"`，`launch_mode="shell_open"`。`resolved_target` 是快捷方式路径本身，不会解析真实目标。
- `RuntimeExecutor.run_app_step()` 在 `shell_open` 时调用 `os.startfile(launch_spec.resolved_target)`，即盲目打开未校验的快捷方式。参数、工作目录和“最小化启动”对 LNK 不生效。
- `tools/check_application_backend_smoke.py` 将上述 LNK 行为作为现有合同固定下来（`shortcut=shell-open,no-process-options`）。
- `WindowsUrlOpener.build_open_spec()` 在存在 `browser_path` 时走 `process` 模式，否则走 `shell_open`。不校验 URL scheme。

GUI 预检：

- `editor/ui/main_window.py` 的 `validate_plan_for_execution()` 只检查**已启用**步骤的必填字段（空路径、空 URL、空命令、非法 shell、非法 wait 秒数）。
- 禁用步骤被 `if not step.enabled: continue` 跳过，因此禁用的不受支持步骤不会阻止试运行或导出。这是现有行为，也是 Basic 合同明确禁止的绕过路径。

### 1.2 许可边界

已确认的现有 Professional / 单一产品许可流：

- `editor/main.py` 在进入工作台前创建 `LicenseManager(PROJECT_ROOT)` 并调用 `validate_current_license()`。有效则打开 `MainWindow`，否则打开 `ActivationWindow`。
- `LicenseManager`（`licensing/license_manager.py`）将许可证存储在 `get_license_dir() / "license.lic"`，即用户数据根下的 `licenses/license.lic`。校验包括文件存在性、可读性，以及 `validate_license_data()` 中的签名、机器码与过期检查。
- 启动时还会调用 `ensure_app_directories()` 和 `shared.data_migration.migrate_legacy_data()`。后者会从已知旧根目录复制 `licenses/license.lic`、方案、日志、设置和模板。
- `editor/ui/main_window.py` **不**引用 `LicenseManager` 或 `validate_current_license()`。导出按钮 `_on_export_exe()` 只做方案预检和文件对话框，然后由 `BuildWorker` 直接调用 `build_single_file_exe()`。
- `tools/build_single_exe.py` **不**检查许可证，也不采集 HWID。
- 嵌入式导出运行器模板同样不导入 `licensing`、不调用 `get_machine_id()`。

结论：当前“导出需要授权”的实际门闩位于编辑器启动，而不是导出函数本身。直接调用 `build_single_file_exe()` 可以绕过 GUI，也不再检查许可。现有有效许可证继续授予当前产品（未来的 Professional）访问权，这一兼容性必须保留。本阶段不得修改 `licensing/`、请求/许可证格式、签名或 HWID 采集。

### 1.3 独立 EXE 导出器

源码证据全部来自 `tools/build_single_exe.py` 与 `editor/ui/main_window.py`。

1. **独立运行器如何生成**  
   `build_single_file_exe(plan_dict, output_exe_path)` 用 `EMBEDDED_TEMPLATE.replace("__PLAN_DATA__", repr(embedded_plan))` 生成自包含脚本 `embedded_launcher.py`，再交给 PyInstaller。方案数据被嵌入为 Python 字面量，不依赖外部 `plan.json`。

2. **运行器是否嵌入完整执行实现**  
   是。嵌入模板没有导入 `runtime.launcher_runtime`，而是复制了一套 `run_app_step` / `run_url_step` / `run_command_step` / `run_wait_step` 与 `main()` 分发逻辑。打包时还会把平台合同序列化进步骤字段：`_application_launch`、`_url_open`、`_command_launch`。

3. **步骤分发如何工作**  
   嵌入式 `main()` 遍历 `EMBEDDED_PLAN["steps"]`；禁用步骤被跳过；按 `type` 分发到四个处理函数；非 wait 步骤按 `delay_after` 睡眠。

4. **导出应用当前是否具备全部四种步骤**  
   是。模板明确包含 Command、CMD/PowerShell（经 `_serialized_command_launch()` 与 `get_command_backend()`）以及 Wait。

5. **依赖如何收集**  
   `_prepare_embedded_plan_and_assets()` 深拷贝方案。若 `AppStep.path` 后缀属于 `PACKABLE_APP_SUFFIXES = {".exe", ".bat", ".cmd", ".com", ".ps1"}` 且文件存在，则复制到临时 `launchflow_assets`，并通过 `__LAUNCHFLOW_ASSET__/` 前缀重写启动路径。`.lnk` 与浏览器路径不打包，仍按原路径执行。

6. **如何调用 PyInstaller**  
   `_get_pyinstaller_command()`：frozen 模式下查找 PATH 中的 `pyinstaller` / `python` / `py`；源码模式下 `import PyInstaller`，缺失时会执行 `sys.executable -m pip install pyinstaller`。实际命令为 `--noconfirm --clean --onefile --windowed`，输出到临时 `dist/`，最后复制到目标路径。导出目录旁还会写入 `{stem}_embedded_debug.py`。

7. **导出前是否检查许可**  
   导出函数本身不检查。GUI 导出发生在已经通过启动许可检查的 `MainWindow` 中。直接调用导出器没有授权门闩。

8. **运行器本身是否执行许可检查**  
   否。嵌入模板没有许可证或 HWID 逻辑。

9. **运行器当前能否强制 Basic 能力集**  
   不能。同一个 `EMBEDDED_TEMPLATE` 编译了 Command / Wait / 脚本应用 / 未解析 LNK 的 `os.startfile` 处理函数。共享打包函数不等于共享相同执行能力；当前实现尚未提供可切换的受限运行器。

10. **当前导出器能否在不复制整套打包实现的前提下支持两个版本**  
    可以共享 `build_single_file_exe()` 的临时目录、资源暂存和 PyInstaller 调用，但必须在调用这些步骤之前加入版本化预检，并生成能力不同的运行器模板。若继续使用当前无限制模板，Basic 导出将静默继承 Professional 处理函数。

其他已确认的导出副作用顺序：`build_single_file_exe()` 首先执行 `output_exe_path.parent.mkdir(...)`，然后解析 PyInstaller、创建临时目录、复制资源、写入调试脚本，最后调用 PyInstaller。当前在这些副作用之前没有方案能力校验。

嵌入式运行器日志目录硬编码为 `%LOCALAPPDATA%\LaunchFlow\logs\launchers\<launcher_name>`（可用 `LAUNCHFLOW_DATA_DIR` 覆盖）。即使将来导出 Basic 运行器，若不改这条路径，也会写入 Professional 数据目录。

### 1.4 应用标识与存储

- `shared/app_paths.py`：`APP_DIR_NAME = "LaunchFlow"`，子目录为 `config`、`data`、`licenses`、`logs`、`plans`、`cache`、`temp`。
- `shared/platform/paths.py` 中 `WindowsPlatformPaths.default_app_root()` 解析为 `%LOCALAPPDATA%\<LaunchFlow|LaunchFlow-Dev>`。相对路径的 `LAUNCHFLOW_DATA_DIR` 会被拒绝。
- `PlanService` 将方案、模板、设置、缓存和日志放在上述用户数据根下。
- 开发模式目录名为 `LaunchFlow-Dev`（`_app_directory_name()`）。
- `migrate_legacy_data()` 会把旧位置的 `license.lic` 和方案复制进当前数据根。若 Basic 复用该迁移逻辑且指向 Professional 根，就会读取或复制 Professional 许可状态。这是关键隔离风险。

`tools/build_editor_release.py` 只负责把编辑器打包为 `LaunchFlow.exe`，不是方案导出器。本阶段不得修改该脚本，也不得调用它。

---

## 2. 产品合同

### 2.1 Basic 能力矩阵（新冻结的产品要求）

| 能力 | Basic | 验收要点 |
| --- | --- | --- |
| 可视化工作流编辑 | 允许 | 仅编辑允许的步骤类型；隐藏 GUI 不能代替数据/执行强制 |
| 本地方案保存/加载 | 允许 | 所有载入入口必须先做 Basic 校验 |
| 顺序执行 | 允许 | 仅 Basic 兼容步骤 |
| 普通本地 EXE 启动 | 允许 | 目标必须是本地、存在的 `.exe` |
| 经严格校验的本地 EXE LNK | 允许 | 必须解析真实目标；禁止盲目 `os.startfile` 未校验快捷方式 |
| HTTP / HTTPS 打开 | 允许 | 仅这些 scheme；默认浏览器 |
| 固定 1 秒步骤间隔 | 允许 | `delay_after` 必须是数值且等于 `1.0`；缺省视为默认 1.0。已写入的不兼容值必须整份拒绝，不得静默改写 |
| 独立 EXE 导出 | 允许 | 不需要激活；只接受 Basic 兼容方案；运行器必须独立强制限制 |
| Command 步骤 | 拒绝 | 含 CMD 与 PowerShell |
| Wait 步骤 | 拒绝 | 整份方案拒绝 |
| 自定义应用参数 | 拒绝 | 非空 `args` |
| 自定义工作目录 | 拒绝 | 非空 `working_dir` |
| 自定义浏览器可执行文件 | 拒绝 | 非空 `browser_path` |
| 非默认“最小化启动” | 拒绝 | `start_minimized` 只能缺省或 `false` |
| 脚本型应用 | 拒绝 | 包括 `.bat`、`.cmd`、`.ps1`、`.com` 及其他脚本后缀 |
| 不支持的 URL scheme | 拒绝 | 如 `file:`、`ftp:`、`javascript:` |
| 网络应用目标 | 拒绝 | UNC 与 URL 形式的应用路径 |
| 不支持或无法解析的 LNK | 拒绝 | 解析失败、目标缺失、非 EXE、不透明目标 |
| 带附加参数的 LNK | 拒绝 | 解析后的快捷方式参数必须为空 |
| 用户可配置的步骤间隔 | 拒绝 | 任何不等于 1 秒的已给值 |
| 未知字段 | 拒绝 | 根对象或步骤中的未知字段 |
| 禁用的不受支持步骤 | 拒绝 | 不得因 `enabled=false` 而跳过 |
| 合法步骤后的不受支持步骤 | 拒绝 | 整份方案拒绝，不得部分执行或静默删除 |

LNK 合同（新冻结的产品要求）：

- 解析快捷方式的真实目标。
- 要求目标是已存在的本地 EXE。
- 拒绝附加参数、脚本目标、网络目标、不支持的目标类型。
- 永远不得回退为盲目执行未校验快捷方式。
- 不得仅因扩展名是 `.lnk` 就认为安全。

Basic 必须免费、无需激活、无需许可证文件、不采集硬件身份、不依赖在线激活。

### 2.2 Professional 兼容性矩阵

| 能力 | Professional（兼容基线） | 说明 |
| --- | --- | --- |
| 现有四种步骤方案 | 保持 | 已确认的现有行为 |
| 高级 App 配置 | 保持 | 参数、工作目录、最小化启动 |
| Command / CMD / PowerShell | 保持 | 现有 `shell` 合同 |
| Wait | 保持 | 现有 `seconds` 与执行语义 |
| 现有 `delay_after` 行为 | 保持 | 可继续使用非 1 秒值，不得为迁就 Basic 而收紧 |
| 方案序列化与往返 | 保持 | `Plan.to_dict()` / `plan_from_dict()` / 现有 schema |
| 独立 EXE 导出 | 保持 | 现有成功 Professional 激活仍是导出前提；不得回归 |
| 离线许可与已有有效许可证 | 保持 | 不得重新设计许可证格式 |
| 当前 LNK `shell_open` 行为 | 保持为现有行为，除非另有产品决定 | 见未决问题 |

不得为了迁就 Basic 而削弱现有 Professional 断言、夹具或冒烟测试。

### 2.3 数据隔离合同（新冻结的产品要求）

| 项目 | Basic | Professional |
| --- | --- | --- |
| 用户数据根 | `%LOCALAPPDATA%\LaunchFlow-Basic` | `%LOCALAPPDATA%\LaunchFlow` |
| 开发模式建议 | `%LOCALAPPDATA%\LaunchFlow-Basic-Dev` | 已确认：`%LOCALAPPDATA%\LaunchFlow-Dev` |

强制要求：

- Basic 不得探测 Professional 许可目录。
- Basic 不得读取 Professional 许可状态。
- Basic 不得清理 Professional 缓存。
- 禁止自动跨版本迁移。
- 禁止共享可变设置、日志、方案或模板。
- 不得意外覆盖另一版本的方案或模板。
- Basic 启动不得对 Professional 根运行 `migrate_legacy_data()`。
- 导出的 Basic 运行器不得把日志写进 `%LOCALAPPDATA%\LaunchFlow`。
- 现有测试钩子 `LAUNCHFLOW_DATA_DIR` 仍可用于隔离测试，但不得成为跨版本共享可变状态的通道。

### 2.4 方案校验合同（新冻结的产品要求）

- 优先保持现有 JSON 方案 schema 不变。
- 不得仅仅为了区分版本而新增 `edition` 字段。
- Basic 必须整份拒绝不兼容方案，而不是静默删除不受支持步骤或改写延迟。
- 校验必须发生在任何执行副作用之前。
- 覆盖入口：直接 JSON 加载、导入方案、模板、方案历史、禁用步骤、直接模型入口、直接执行器入口、导出入口。
- 只要存在一个不受支持步骤，整份方案都要被拒绝。
- Professional 必须继续接受现有合法方案。
- Basic 校验不得通过直接导入方案、禁用步骤、或直接调用导出器而被绕过。

Phase 0 将上述规则实现为测试专用模块 `tools/dual_edition_phase0_contract.py`。该模块尚未接入生产加载、GUI、运行时或导出器。

---

## 3. 独立 EXE 导出合同

### 3.1 Basic 导出（新冻结的产品要求）

- 不需要激活、许可证文件或 HWID。
- 只接受 Basic 兼容方案。
- 校验必须发生在以下副作用之前：创建不必要的临时文件、不必要地创建输出目录、调用 PyInstaller、写入 `{stem}_embedded_debug.py` 或其他导出产物。
- 导出的运行器必须独立强制 Basic 限制，不得暴露 Command、CMD、PowerShell 或 Wait 执行。
- 运行时不得要求许可证或采集硬件身份。
- 运行器不得静默继承无限制的 Professional 处理函数。
- 不得把 `.bat` / `.cmd` / `.com` / `.ps1` 当作可打包 Basic 应用资源。
- 若仍写出调试脚本，其能力必须与受限 Basic 运行器一致，不得泄漏 Professional 处理函数。

### 3.2 Professional 导出（兼容基线）

- 现有成功 Professional 激活仍是前提。
- 现有受支持工作流语义、命令执行和导出能力不得回归。
- `_prepare_embedded_plan_and_assets()` 当前会为 command/url/app 序列化启动合同，并在文件存在时打包 exe/bat/cmd/com/ps1。该 Professional 行为是基线，不是缺陷。
- Phase 0 用合成夹具调用准备函数以锁定序列化期望，但**不会**调用 `build_single_file_exe()`，也**不会**调用 PyInstaller。

### 3.3 共享基础设施与运行时隔离（建议的未来架构）

两者可以共享：临时目录辅助、资源暂存、PyInstaller 命令组装、输出复制。

两者不得共享：无限制的嵌入式执行模板，或会把 Command/Wait/脚本/未校验 LNK 编译进 Basic 运行器的分发逻辑。

建议路径（尚未实现）：

1. 在任何打包副作用之前，加入版本化导出预检。
2. 为 Basic 使用受限运行器模板（或显式能力白名单），为 Professional 保留当前模板。
3. Basic 运行器日志写入 `LaunchFlow-Basic`（或等价的版本私有位置）。
4. Professional 导出在导出点保留授权检查，而不仅仅依赖进程此前已进入主窗口。直接调用生产导出器不得成为 Basic 绕过路径；Professional 直接调用仍须遵守其授权合同。

### 3.4 剩余技术风险

- 当前模板复制了运行时逻辑，两套实现可能再次漂移。
- `_get_pyinstaller_command()` 在源码模式下可能自动 `pip install`，导出预检失败时不得触发该路径。
- 调试脚本会把完整运行器源码写到用户选择的输出目录旁边。
- 嵌入式日志路径硬编码为 `LaunchFlow`。
- `_serialized_application_launch()` 使用 `path_exists=lambda _path: True`，因此不会在导出时解析或验证 LNK 目标。
- 现有应用后端与导出冒烟测试把“盲目 shell-open LNK”视为 Professional 基线；Basic 不得复用该路径。
- 若只做 GUI 隐藏而不改模板，Basic 导出的 EXE 仍能执行 Professional-only 步骤。

---

## 4. 安全与隔离结论

已确认的现有风险（不是攻击说明，而是后续实现必须关闭的边界）：

- 编辑器启动总会走到许可校验与（可能的）遗留迁移，包括 `license.lic` 复制。
- 数据根名称只有 `LaunchFlow` / `LaunchFlow-Dev`。不存在 `LaunchFlow-Basic`。
- 当前 LNK 执行不解析目标，可能打开脚本、网络位置或带参数的快捷方式。
- 当前 URL 打开不限制 scheme。
- 当前应用启动允许脚本后缀，且导出器会打包这些脚本。
- 禁用步骤可绕过 GUI 预检并进入试运行/导出。
- `build_single_file_exe()` 没有许可或能力门闩。
- 导出运行器日志可以写入共享的 Professional 用户数据目录。

新冻结的隔离/安全要求：

- Basic 与 Professional 使用独立可变数据根。
- Basic 代码路径不得探测或读取 Professional 许可状态，不得采集 HWID。
- Basic 运行器与编辑器必须在数据、执行、导出和运行时层强制能力边界。
- 所有 Phase 0 测试只使用合成路径、URL 与快捷方式解析表。不得读取真实 AppData 许可内容、真实用户方案、私钥或真实机器身份。

---

## 5. 回归合同

每一条接受/拒绝决定都由合成夹具和 `tools/check_dual_edition_contract_smoke.py` 固定。

必须始终为真：

- Professional 是兼容基线。现有四步方案、高级 App 配置、命令配置、Wait、序列化往返和现有导出准备合同不得被削弱。
- Basic 校验不能通过直接导入方案而被绕过。
- 禁用步骤不能绕过校验。
- 导出校验不能通过直接调用导出器而被绕过。
- Basic 导出运行器不能执行 Professional-only 步骤。
- 不得发生静默兼容降级（删除步骤、改写延迟、把不受支持目标当成普通 EXE）。
- 现有冒烟测试和 `tools/check_platform_coupling_baseline.json` 不得被修改来迁就 Basic。

Phase 0 证明方式：合同模块对所有列出入口执行同一套规则；源码检查证明当前生产导出器/运行时**尚未**实施 Basic 边界。这是预期差距，不是已完成实现。

---

## 6. 交付物

| 路径 | 作用 |
| --- | --- |
| `tools/fixtures/dual_edition_phase0/basic_valid/` | 8 个合成 Basic 合法方案 |
| `tools/fixtures/dual_edition_phase0/basic_invalid/` | 17 个合成 Basic 非法方案 |
| `tools/fixtures/dual_edition_phase0/professional/` | 7 个 Professional 兼容夹具 |
| `tools/fixtures/dual_edition_phase0/shortcut_resolutions.json` | 仅用于测试的合成 LNK 解析表，不是方案 schema |
| `tools/fixtures/dual_edition_phase0/manifest.json` | 夹具完整性清单 |
| `tools/dual_edition_phase0_contract.py` | 测试专用合同规格；未接入生产 |
| `tools/check_dual_edition_contract_smoke.py` | 合同、导出预检、Professional 往返与源码边界测试 |
| `docs/dual-edition-phase0-contract.md` | 本文件 |

本阶段没有改写已有的脏文件：`.ai/*`、`CHANGELOG.md`、`docs/architecture.md` 及其他已有未提交文档。

---

## 7. 未决问题

1. Professional 是否继续对 LNK 使用现有的未解析 `os.startfile` 行为，还是在未来阶段采用更严格的解析？默认建议：Professional 保持现有行为，除非产品明确要求收紧。
2. Basic 的 1 秒延迟是否只接受精确的数值 `1` / `1.0`（本阶段已如此冻结），还是允许误差？
3. 映射网络驱动器（有盘符但指向远程卷）是否视为“网络目标”？当前冻结范围覆盖 UNC 与 URL 风格路径；映射盘需要产品决策。
4. `.com` 是否视为“普通本地 EXE”？本阶段将其与脚本/非普通目标一并拒绝。
5. 是否存在（或是否需要）除历史列表之外的正式“导入方案”UI？合同已覆盖该入口，即使当前 UI 主要是历史载入。
6. Professional 导出是否应在导出时重新校验许可证，而不仅仅依赖启动时已经进入 `MainWindow`？建议重新校验以保持授权合同，但不能造成现有成功激活用户回归。
7. 两个版本将如何分发（两个安装包、两个编辑器目标、还是同一仓库的两套打包入口）？不影响 Phase 0 合同，但会影响 Phase 1 以后的启动入口工作。
8. Basic 开发模式目录是否确定为 `LaunchFlow-Basic-Dev`？
9. 导出的 Basic 运行器日志应写到 `LaunchFlow-Basic/logs/launchers/...`，还是完全独立的位置？
10. 现有 `validate_export_smoke.py` 依赖打包脚本应用并运行 EXE。后续阶段如何在不削弱该 Professional 冒烟测试的前提下，增加不调用 PyInstaller 的 Basic 导出合同？
11. 实现 LNK 解析应使用哪套 Windows API（例如 `IShellLink` / COM）？Phase 0 只冻结解析结果合同，不指定 API。
12. 空字符串参数、仅空白的工作目录、或字符串形式的 `"1.0"` 延迟应如何处理？本阶段冻结为：空白工作目录视为空（允许）；非空参数拒绝；字符串延迟拒绝，不做强制类型转换。
13. Basic 编辑器是否应省略 Command/Wait 模板，以避免把 Professional 模板写入 Basic 数据目录？建议省略，但这属于后续 GUI/模板工作。
14. `BuildWorker` / 直接 `build_single_file_exe()` 调用在双版本下的公开 API 形状尚未决定。

若某个问题无法从现有实现证据确定，不得编造实现细节。上述问题必须在实施前得到回答或被明确接受为默认值。

---

## 8. Phase 1 前置清单与建议

在 Phase 1 开始前确认：

- [ ] 本文件中的 Basic / Professional 矩阵仍被接受。
- [ ] 合成夹具与 `tools/check_dual_edition_contract_smoke.py` 保持通过。
- [ ] 生产文件哈希未因 Phase 0 而改变。
- [ ] 不修改 `licensing/`、许可证格式、HWID、发布标签或 `v0.1.0-beta.2`。
- [ ] 不削弱现有 Professional 冒烟测试或耦合基线。
- [ ] 已同意：默认 Professional 保持当前 LNK `shell_open` 行为。
- [ ] 后续实现必须先校验、后产生导出副作用。
- [ ] Basic 数据根名称与“禁止迁移/探测 Professional 许可”的规则已获同意。

建议的最小且安全的 Phase 1 任务（不要自动开始）：

将已冻结的 Basic 方案校验规则提升为 `shared/` 中可在生产使用、但默认不改变当前 Professional 路径的纯函数模块（含可注入的 LNK 解析接口），并用 Phase 0 夹具进行测试。不要改 GUI，不要改启动授权流，不要改 `EMBEDDED_TEMPLATE`，不要调用 PyInstaller，不要切换数据目录，也不要引入 Basic/Professional 启动入口。目标是得到一个可复用的校验器，供后续入口接入使用，同时保持现有 Professional 行为不变。

明确推迟到更后阶段：版本化编辑器入口、数据目录切换、导出模板拆分、运行时能力隔离，以及任何许可格式工作。

---

## 9. 源码证据索引

| 主题 | 路径与符号 |
| --- | --- |
| 方案模型 | `shared/models.py`：`Plan`、`AppStep`、`UrlStep`、`CommandStep`、`WaitStep`、`plan_from_dict()` |
| 结构校验 | `shared/plan_schema.py`：`validate_plan_dict()`、`SUPPORTED_STEP_TYPES` |
| 方案服务 | `editor/services/plan_service.py`：`PlanService.load_plan()`、`save_plan()`、`DEFAULT_TEMPLATES` |
| 启动许可 | `editor/main.py`：`LicenseManager.validate_current_license()`、`MainWindow`、`ActivationWindow`、`migrate_legacy_data()` |
| GUI 预检与导出 | `editor/ui/main_window.py`：`validate_plan_for_execution()`、`_prepare_plan_for_execution()`、`_on_export_exe()`、`BuildWorker.run()` |
| 运行时执行 | `runtime/launcher_runtime.py`：`RuntimeExecutor.run_plan()` 及四个 `run_*_step` 方法 |
| 应用启动/LNK | `shared/platform/applications.py`：`classify_target()`、`launch_mode="shell_open"` |
| URL 打开 | `shared/platform/urls.py`：`WindowsUrlOpener.build_open_spec()` |
| 数据路径 | `shared/app_paths.py`：`APP_DIR_NAME`；`shared/platform/paths.py`：`WindowsPlatformPaths` |
| 遗留迁移 | `shared/data_migration.py`：`migrate_legacy_data()` 复制 `license.lic` |
| 许可存储 | `licensing/license_manager.py`：`get_license_dir() / "license.lic"`、`validate_current_license()` |
| 方案导出器 | `tools/build_single_exe.py`：`EMBEDDED_TEMPLATE`、`_prepare_embedded_plan_and_assets()`、`_get_pyinstaller_command()`、`build_single_file_exe()` |
| 编辑器打包 | `tools/build_editor_release.py`：`build_editor_release()`（本阶段未改动、未执行） |

---

## 附录 A — Phase 0 之后的产品决定（Phase 1a 记录）

本附录在不改写上文历史结论与未决问题原文的前提下，记录 Phase 1a 实施时确认的产品决定。这些决定补充、而不是替换第 2 节已冻结的合同；其中部分内容回答了第 7 节当时列出的未决问题。已实现行为与尚未接线的后续工作在此分开说明。

### A.1 映射网络驱动器

决定：映射网络驱动器视为网络目标，Basic 必须拒绝。

仅凭词法检查（盘符路径、UNC、URL 形式）不能认定 `Z:\Apps\example.exe` 这类路径是本地路径。Basic 策略核心必须通过可注入的驱动器/路径分类接口判定盘符是否指向远程卷。分类结果为远程、未知，或分类不可用时，必须失败关闭。

Phase 1a 只引入该可注入接口与策略行为，不实现真实 Windows API 适配器。真实适配器留到 Phase 1b。不得声称词法路径检查可以单独发现映射网络驱动器。

### A.2 Professional 导出授权在 Phase 1 保持不变

决定：在整个 Phase 1 期间，Professional 的现有 EXE 导出授权行为保持不变，并且需要在后续独立任务中审计。本阶段不得修改许可校验、HWID 采集、导出授权实现，也不得把导出授权检查接入生产导出器。

### A.3 实施边界说明

Phase 1a 将 Basic 方案校验提升为 `shared/basic_policy.py` 中可复用的生产模块。该模块默认不改变当前 Professional 路径，也尚未接入 GUI、运行时执行器、应用入口或 EXE 导出器。

上文第 2.4 节所述“Phase 0 测试专用模块尚未接入生产”的历史事实仍然成立：`tools/dual_edition_phase0_contract.py` 仍未接线。Phase 1a 模块同样尚未接线到加载、GUI、执行或导出入口。接入工作属于 Phase 1b，不得把尚未接线的能力写成已完成的产品行为。

---

## 附录：Phase 1b 实施备注（2026-11-24，Asia/Shanghai）

本附录不改写 Phase 0 已冻结的历史决策。

- 映射网络驱动器在合同中已被拒绝。Phase 1b 通过注入或真实的 Windows 盘符分类器实施该拒绝；词法盘符路径不会被自动当成本地路径。
- Professional 导出授权在 Phase 1 期间保持不变，仍需后续单独审计。Phase 1b 没有修改许可校验、HWID 采集或导出授权逻辑。
- Basic 校验已按门控方式接入现有方案入口，但默认产品路径仍是当前 Professional / 单一产品行为，因为启动入口尚未引入。
