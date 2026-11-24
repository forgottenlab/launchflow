# LaunchFlow 双版本架构 — Phase 2 启动入口、数据隔离与 Basic 运行器

- 状态：Phase 2 已实现明确的 Basic / Professional 启动入口、Basic 数据目录隔离，以及受限的 Basic 导出运行器；这不是一次新的公开发布
- 日期：2026-11-24（Asia/Shanghai）
- 新增或接线模块：`editor/launch.py`、`editor/main_basic.py`、`tools/basic_embedded_runner.py`、`tools/run_editor_basic_dev.ps1`
- 测试：`tools/check_dual_edition_phase2_smoke.py`
- 上游：`docs/dual-edition-phase1b-windows-adapters.md`、`docs/dual-edition-phase0-contract.md`

本文记录已经实现的 Phase 2 行为。不得把下文“已知限制”写成已经交付的公开发布能力，也不得把本次实现理解为已经替换 `v0.1.0-beta.2` 的公开产物。

Phase 2 **没有**修改最近公开发布检查点 `v0.1.0-beta.2`，没有调用 PyInstaller，没有生成发布 EXE，没有审计或改变 Professional 导出授权，也没有开始后续阶段。`docs/architecture.md` 与 `CHANGELOG.md` 当时存在未提交的本地修改，因此本阶段没有改这两份文件；它们需要在本地改动稳定后另作更新。

---

## 1. 启动入口

当前产品入口仍然是 Professional / 单一产品路径：

| 入口 | 启动方式 | 进程级版本上下文 | 授权 | 数据目录 |
| --- | --- | --- | --- | --- |
| `editor/main.py` | `python -m editor.main`，默认打包为 `LaunchFlow.exe` | 未设置，视为 Professional | 保持现有离线许可与激活窗口 | `%LOCALAPPDATA%\LaunchFlow` |
| `editor/main_basic.py` | `python -m editor.main_basic`，打包目标为 `LaunchFlow-Basic.exe` | 显式设置为 `basic` | 不校验许可证，不采集 HWID | `%LOCALAPPDATA%\LaunchFlow-Basic` |

公共逻辑位于 `editor/launch.py`。Professional 入口会在创建数据目录之前把进程上下文复位为未设置，避免残留的 Basic 上下文把当前产品路径改成 Basic。Basic 入口则必须在 `ensure_app_directories()` 之前设置 Basic 上下文。

当前入口的 Windows 进程标识仍是 `forgottenlab.launchflow.editor`。Basic 入口使用单独的 `forgottenlab.launchflow.editor.basic`，避免两个版本在任务栏中被当成同一个进程。这只是对现有 `configure_windows_app_id()` 门面传入不同标识，没有新增 Windows API 调用点。

开发模式继续通过进程级 `LAUNCHFLOW_DATA_DIR` 切换，而不是改 `get_app_data_dir()` 的默认计算：

- Professional：`tools/run_editor_dev.ps1` 仍指向 `%LOCALAPPDATA%\LaunchFlow-Dev`，并启动 `python -m editor.main`
- Basic：新增 `tools/run_editor_basic_dev.ps1`，指向 `%LOCALAPPDATA%\LaunchFlow-Basic-Dev`，并启动 `python -m editor.main_basic`

本次确认 Phase 0 中的未决问题：Basic 开发目录采用 `LaunchFlow-Basic-Dev`。

---

## 2. 数据目录隔离

`shared/app_paths.py` 在 Basic 上下文激活时把目录名切换为 `LaunchFlow-Basic`，Professional / 未设置上下文继续使用 `LaunchFlow`。常量 `APP_DIR_NAME` 仍为 `"LaunchFlow"`，以保持现有兼容测试不变。

强制规则：

- Basic 不得探测、读取、清理或迁移 `%LOCALAPPDATA%\LaunchFlow` 或 `LaunchFlow-Dev`
- `migrate_legacy_data()` 在 Basic 上下文中直接失败关闭并跳过，不检查任何遗留根目录，也不复制 `license.lic`
- Basic 启动路径本身不会调用遗留迁移
- 若 `LAUNCHFLOW_DATA_DIR` 指向 Professional 默认根（`LaunchFlow` 或 `LaunchFlow-Dev`），Basic 会拒绝该覆盖，而不是回退到 Professional 目录
- 指向其他绝对路径的测试覆盖仍然可用，但不得成为两个版本共享可变状态的通道

---

## 3. Basic 导出运行器

Professional 的 `EMBEDDED_TEMPLATE` 保持不变，包括 Command、Wait、脚本应用以及 LNK 的 `os.startfile` 行为。Basic 运行器位于单独模块 `tools/basic_embedded_runner.py`，由 `build_single_file_exe()` 在 Basic 上下文中选用。

两者可以继续共享临时目录、资源暂存和 PyInstaller 命令组装。它们不得共享无限制的嵌入式执行模板。

Basic 运行器限制：

- 不嵌入 `run_command_step` / `run_wait_step`
- 不处理 PowerShell 脚本或其他脚本后缀应用
- 不通过 `os.startfile(path)` 盲目打开快捷方式
- 导出时若方案包含 `.lnk`，必须先解析为本地 `.exe` 后再序列化为进程启动；解析失败则在创建输出目录和查找 PyInstaller 之前失败关闭
- 只把现有的本地 `.exe` 当作可打包资源，不会打包 `.bat` / `.cmd` / `.com` / `.ps1`
- 运行器日志写入 `LaunchFlow-Basic`（或非 Professional 的测试覆盖目录）
- 若仍写出 `{stem}_embedded_debug.py`，其能力与受限 Basic 运行器一致
- 不导入许可模块，也不采集硬件身份

Professional 导出授权仍待后续单独审计。本次没有把授权检查加进 `build_single_file_exe()`。

---

## 4. 编辑器界面裁剪

Professional / 当前产品入口的工作台保持原样：仍然提供“+ 命令”“+ 等待”、应用启动参数，以及可编辑的后续延迟。

Basic 入口会在同一套 `MainWindow` 上裁剪 Professional-only 能力，而不是另做一套窗口：

- 不显示“+ 命令”和“+ 等待”按钮，直接调用添加接口也会被拒绝
- 不显示应用启动参数，也不显示可自定义的 `delay_after` 控件；保存步骤时固定为无参数、间隔 1 秒
- 添加应用时的文件选择只包含本地 `.exe` / `.lnk`
- 首次写入 Basic 数据目录的 `app_templates.json` 不含 Command / Wait；即使文件被污染，加载时也会过滤
- 空状态提示、侧栏名称和标题栏会标明 LaunchFlow Basic，避免看起来仍是完整 Professional 工作台

Basic 仍然可以先添加一个空白网页步骤，再补全 URL。缺失 URL 会在加载、试运行或导出时被拒绝，而不是在点击“+ 网页”时直接失败。

当前 GUI 本身在两个版本中都没有提供工作目录或“最小化启动”编辑控件。这是已有界面范围，不是本次为 Professional 新增的能力。Basic 仍会通过方案校验拒绝这些字段。

## 5. 打包与发布路径

当前默认打包命令仍然只生成 Professional 编辑器：

```powershell
python tools/build_editor_release.py
```

它继续使用 `editor/main.py`，输出 `LaunchFlow.exe`。Basic 需要显式选择：

```powershell
python tools/build_editor_release.py --edition basic
```

这会使用 `editor/main_basic.py`，输出 `LaunchFlow-Basic.exe`。本次实现没有实际调用 PyInstaller，也没有把 Basic 编辑器发布成新的公开 Beta 资产。`v0.1.0-beta.2` 仍是最近的公开发布检查点。

---

## 6. 测试覆盖

`tools/check_dual_edition_phase2_smoke.py` 覆盖：

1. 当前产品入口保持未设置 / Professional，不会把默认路径改成 Basic
2. Basic 入口会设置进程级 Basic 上下文，且发生在创建数据目录之前
3. Basic 入口不导入或调用许可、HWID 或遗留迁移
4. Basic 默认数据根为 `LaunchFlow-Basic`，不会创建或读取 Professional 数据
5. 指向 `LaunchFlow` / `LaunchFlow-Dev` 的覆盖在 Basic 下失败关闭
6. `migrate_legacy_data()` 在 Basic 下不复制 Professional 许可或方案
7. Professional `EMBEDDED_TEMPLATE` 的哈希与 Command / Wait / LNK `shell_open` 合同保持不变
8. Basic 运行器模板通过 Phase 0 冻结的能力边界检查
9. Basic 导出在拒绝 Command 方案时不会查找 PyInstaller，也不会创建输出目录或调试脚本
10. 默认编辑器打包入口仍是 `LaunchFlow.exe` / `editor/main.py`；Basic 打包入口是独立的
11. Basic 默认模板和 `load_templates()` 不含 Command / Wait；Professional 默认模板保持不变
12. Basic 工作台隐藏 Command / Wait 按钮、应用参数和自定义延迟；Professional 工作台这些控件仍然可见

现有 Phase 0 / 1a / 1b 合同与策略测试，以及无副作用的路径、迁移、平台耦合、应用/URL 与文档冒烟测试应继续通过。

---

## 7. 平台耦合说明

Phase 2 没有新增核心包中的 Windows API 调用。Basic 入口复用已有的 `configure_windows_app_id()` 门面。新增的工具边界包括：

- `tools/basic_embedded_runner.py`：独立 EXE 运行器中的 `MessageBoxW`、`LOCALAPPDATA` 以及仅用于 http/https 的 `os.startfile(url)`
- `tools/run_editor_basic_dev.ps1`：进程级数据目录覆盖与源码启动

这些边界已加入 `tools/check_platform_coupling_smoke.py` 的工具入口扫描，便于后续审查。它们不属于新的核心耦合。

---

## 8. 已知限制

- 本次没有发布独立的 Basic 安装包或公开 GitHub Release 资产。文档描述的是仓库中已经落地的实现与打包入口。
- Professional 导出授权仍依赖“此前已进入主窗口”，直接调用 `build_single_file_exe()` 的审计仍待后续任务。
- Basic 编辑器仍复用现有 `MainWindow`，只按版本隐藏或拒绝 Professional-only 能力，没有做成完全独立的第二套界面。
- 工作目录和“最小化启动”本来就不在当前 GUI 中编辑；它们继续只存在于方案模型和 Professional 运行/导出路径里。
- 本阶段未修改 `docs/architecture.md` 和 `CHANGELOG.md`。

---

## 9. 建议的下一阶段

建议的下一阶段不要自动开始。在获得单独授权之前，不应把 Basic 宣传成已经对外发布的产品。

推荐顺序：

1. 单独审计 Professional 导出授权，避免直接调用导出器绕过现有激活前提。
2. 在本地文档改动稳定后，把本阶段结论同步进 `docs/architecture.md` 和 `CHANGELOG.md`。
3. 若要作为产品发布 Basic，再补发布说明和经过授权的打包构建。

---

## English Summary

Phase 2 adds an explicit Basic launch entry, LaunchFlow-Basic data isolation, a restricted Basic export runner, and Basic workbench trimming, while leaving the current product entry on the Professional path. `python -m editor.main` / `LaunchFlow.exe` still uses `%LOCALAPPDATA%\LaunchFlow`, keeps offline licensing, and shows the full existing UI, including Command, Wait, application arguments, and custom delays. `python -m editor.main_basic` / the `LaunchFlow-Basic.exe` packaging target sets process-wide Basic context first, skips license and legacy migration, refuses to read or fall back to Professional data, and hides Professional-only templates and advanced App controls. The Professional `EMBEDDED_TEMPLATE` is unchanged; Basic export uses a separate runner that cannot embed Command, Wait, script apps, or unvalidated shortcut shell-open behavior, and writes logs under LaunchFlow-Basic. This is an in-repo implementation, not a new public Beta release; `v0.1.0-beta.2` remains the latest published artifact. `docs/architecture.md` and `CHANGELOG.md` still need a later pass after local edits settle.
