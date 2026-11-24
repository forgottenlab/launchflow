# LaunchFlow 双版本架构 — Phase 1b Windows 适配器与门控接入

- 状态：Phase 1b 已实现真实 Windows 快捷方式解析与盘符分类适配器，并把 Basic 校验以门控方式接到方案入口；默认产品路径仍是现有 Professional / 单一产品行为
- 日期：2026-11-24（Asia/Shanghai）
- 新增模块：`shared/platform/windows_shell_links.py`、`shared/platform/windows_drives.py`、`shared/edition_policy.py`
- 测试：`tools/check_basic_policy_phase1b_smoke.py`
- 上游：`docs/dual-edition-phase1a-basic-policy.md`、`docs/dual-edition-phase0-contract.md`

本文记录已经实现的 Phase 1b 行为。不得把下文“已知限制”或“建议的下一阶段”写成已经交付的产品能力。

Phase 1b **没有**引入 Basic / Professional 启动入口，没有切换数据目录身份，没有修改 `EMBEDDED_TEMPLATE`，也没有改变许可校验、HWID 采集或 Professional 导出授权行为。本次没有调用 PyInstaller，没有生成 EXE，也没有开始下一阶段。

---

## 1. 适配器架构

策略核心 `shared/basic_policy.py` 仍然保持无副作用：它只通过注入的 `FilesystemInspector`、`DriveClassifier` 和 `ShortcutResolver` 做判定。Phase 1b 把真实操作系统调用放到专用适配器中，而不是写进策略核心、运行时启动器或导出模板。

| 模块 | 公共接口 | 职责 |
| --- | --- | --- |
| `shared/platform/windows_shell_links.py` | `WindowsShortcutResolver`、`read_windows_shortcut()`、`write_windows_shortcut()` | 通过 IShellLinkW / IPersistFile 解析或写入快捷方式 |
| `shared/platform/windows_drives.py` | `WindowsDriveClassifier` | 通过 Windows 卷 API 判断路径所在卷是本地还是远程 |
| `shared/edition_policy.py` | `EditionContext`、`edition_scope()`、`enforce_basic_policy_on_ingress()`、`build_production_basic_policy_dependencies()` | 版本门控、生产依赖装配，以及入口处的失败关闭强制校验 |

`write_windows_shortcut()` 只用于测试或工具写入快捷方式文件，不会执行目标。生产校验路径只调用解析接口。

生产依赖由 `build_production_basic_policy_dependencies()` 装配：

- 文件系统检查：`OsFilesystemInspector`（`os.path.exists` / `os.path.isdir`）
- Windows 上：真实的 `WindowsDriveClassifier` 与 `WindowsShortcutResolver`
- 非 Windows：失败关闭的不可用适配器
- 测试可在 `EditionContext.dependencies` 中注入伪造实现，不必调用真实 COM / 卷 API

默认不会在导入 `shared.platform` 时加载这些适配器；它们只在 Basic 门控被激活并需要生产依赖时，或测试直接导入时才会加载。

---

## 2. 使用的 Windows API

快捷方式解析使用 COM：

- `CoInitializeEx` / `CoUninitialize`（`COINIT_APARTMENTTHREADED`）
- `CoCreateInstance(CLSID_ShellLink, IID_IShellLinkW)`
- `IUnknown::QueryInterface(IID_IPersistFile)`
- `IPersistFile::Load`（`STGM_READ`）
- `IShellLinkW::GetPath`（优先 `SLGP_RAWPATH`，必要时再尝试无标志读取）
- `IShellLinkW::GetArguments`
- `IShellLinkW::GetWorkingDirectory`

解析器**不会**调用 `IShellLinkW::Resolve`，以避免搜索、跟踪或 UI 副作用。它也**不会**调用 `os.startfile`，不会启动子进程，不会因为扩展名是快捷方式就接受该步骤。

盘符分类使用 `kernel32`：

- `GetVolumePathNameW` 得到卷根路径
- `GetDriveTypeW` 判断卷类型

判定规则：

- `DRIVE_REMOTE` → `remote`（包含映射网络驱动器和其他远程卷）
- `DRIVE_FIXED` / `DRIVE_REMOVABLE` / `DRIVE_CDROM` / `DRIVE_RAMDISK` → `local`
- `DRIVE_NO_ROOT_DIR` 或 API 失败 → `unavailable`
- `DRIVE_UNKNOWN` 或其他未识别值 → `unknown`

词法检查仍然由策略核心拒绝 UNC 和 URL 形式路径，但不能单独发现映射盘。盘符绝对路径只有在分类器明确返回 `local` 时才会被接受。

这两个适配器都接受可注入的底层函数，便于在不改变系统状态的情况下测试映射盘等分支。

---

## 3. 失败关闭行为

快捷方式：

- 路径为空、文件不存在、内容不是可加载的快捷方式、COM 初始化失败、`Load` / `GetPath` 失败，都会抛出异常或返回 `status != "resolved"`
- 目标路径为空视为未解析
- 策略核心继续拒绝带参数、带工作目录、指向非本地 EXE，或缺少解析器的快捷方式
- 异常由策略核心转为 `basic_lnk_resolver_error`；无法解析则转为 `basic_invalid_lnk`

盘符分类：

- 无法得到卷根且无法安全回退到词法盘符根 → `unavailable`
- `GetDriveTypeW` 抛错 → `unavailable`
- 未知或不支持的类型不会被当成本地
- 不存在的 UNC 不得被分类为 `local`；当前主机上通常是 `unavailable` 或 `remote`，两者都是失败关闭或明确远程

当 Basic 版本上下文处于活动状态但无法提供 Windows 适配器时，生产装配会注入不可用实现，策略因此失败关闭，而不会退回未校验的 shell 打开。

---

## 4. 入口接线如何门控，以及 Professional 行为如何保持不变

当前产品仍然没有 Basic / Professional 启动入口。如果在所有现有入口无条件执行 Basic 校验，含 Command / Wait / 高级 App 步骤的现有方案会被拒绝。这是不可接受的。

因此 Phase 1b 引入显式版本上下文，而不是改启动入口或数据目录：

- 进程默认上下文为“未设置”，视为当前 Professional / 单一产品路径
- 只有当上下文明确为 `basic` 时，`is_basic_edition_active()` 才为真
- `professional`、空值或未设置都不会启用 Basic 校验
- 上下文同时支持进程级默认值（供未来启动入口使用）和任务级 `edition_scope()`（供测试和显式覆盖使用）。进程级默认值可被后台试运行 / 导出线程看到；Phase 1b 不会在启动时设置它

门控函数 `enforce_basic_policy_on_ingress()`：

- 当前产品路径上是空操作
- 在 Basic 上下文中，于模型反序列化、执行或打包副作用之前调用 `validate_basic_plan_document()` 或 `validate_basic_plan()`
- 拒绝时抛出 `BasicPolicyViolation`，并带上结构化结果

已接入的入口：

| 入口 | 接线位置 | 默认 Professional 行为 |
| --- | --- | --- |
| 直接 JSON 加载、历史方案加载 | `PlanService.load_plan()` 在 `plan_from_dict()` 之前 | 保持原样加载 |
| 模板步骤 | `PlanService.create_step_from_template()` | 仍可创建 Command / Wait |
| 新建应用步骤 | `PlanService.create_app_step()` | 保持原样创建 |
| 直接执行器调用、试运行 | `RuntimeExecutor.run_plan()` 在任何步骤执行之前 | 仍执行全部四种步骤；LNK 仍走现有 `shell_open` |
| 导出 | `build_single_file_exe()` 在创建输出目录和查找 PyInstaller 之前 | 现有导出流程与授权保持不变 |
| GUI 预检 | `validate_plan_for_execution()` | 现有“只检查启用步骤”的预检保持不变 |

这些挂钩在当前路径上只增加一次上下文检查，不会改方案 schema、不会改 `EMBEDDED_TEMPLATE`，也不会改 Professional 对 LNK 的 `os.startfile` 默认启动方式。

---

## 5. 测试覆盖

`tools/check_basic_policy_phase1b_smoke.py` 覆盖：

1. 默认上下文不是 Basic，Professional 方案不会被门控拒绝
2. 注入的盘符分类：本地、远程/映射、未知、不可用，以及 API 失败
3. 真实分类器把系统盘和临时目录判为本地；不存在的 UNC 不会被判为本地
4. 真实 IShellLink 解析器处理合成本地 EXE 快捷方式，并能读出参数与工作目录
5. 缺失或损坏的快捷方式失败关闭；解析过程不调用 `os.startfile`，也不启动子进程
6. 生产依赖可以把真实本地 EXE 快捷方式交给策略核心并接受；注入的映射盘分类会被拒绝
7. `PlanService.load_plan()` 与模板在 Professional 下接受 Command / Wait，在 Basic 下拒绝
8. `RuntimeExecutor.run_plan()` 在 Professional 下仍会分派命令步骤（测试中已替换真实执行），在 Basic 下于执行前拒绝
9. `build_single_file_exe()` 在 Professional 下仍会走到现有 PyInstaller 查找；在 Basic 下于查找 PyInstaller 或创建输出目录之前拒绝。测试会拦截该查找，不会真正调用 PyInstaller
10. GUI 预检在 Professional 下仍跳过禁用步骤；在 Basic 下会校验禁用的不受支持步骤
11. Professional 的 LNK `shell_open` 启动合同保持不变
12. 显式 `professional` 标签不会启用 Basic 校验

现有 Phase 0 合同测试与 Phase 1a 策略测试必须继续通过。真实快捷方式测试只在临时目录创建合成 `.lnk`，并在结束后清理；不会读取用户 AppData 中的真实快捷方式，也不会执行解析到的目标。

---

## 6. 已知限制

- 仍然没有 Basic / Professional 启动入口。门控已经接到入口，但当前产品默认不会激活 Basic。
- 没有切换数据目录。Basic 合同中的 `%LOCALAPPDATA%\LaunchFlow-Basic` 尚未实施，也禁止探测或迁移 Professional 数据。
- 没有修改 `EMBEDDED_TEMPLATE`。即使将来激活 Basic，导出的独立 EXE 仍会嵌入当前含 Command / Wait 的 Professional 运行器，除非后续阶段替换 Basic runner。
- 没有单独审计或改变 Professional 导出授权。导出路径在当前产品中仍可直接调用 `build_single_file_exe()`。
- 没有实现完整的 Windows Installer / 仅 ID List 快捷方式恢复。若必须调用 `Resolve()` 才能得到目标路径，适配器失败关闭。
- 真实环境里未必存在映射网络驱动器。映射盘分支通过注入的 `GetDriveTypeW` 结果覆盖；真实 API 测试覆盖本地卷，以及不得把 UNC 当成本地。
- `RuntimeExecutor.run_app_step()` 等单步方法本身没有单独门控；完整方案入口是 `run_plan()`。Professional 默认仍按路径扩展名对 LNK 做 `shell_open`。
- `plan_from_dict()` 和 `validate_plan_dict()` 没有修改。Basic 的未知字段检测仍然只发生在文档入口。

---

## 7. 建议的下一阶段

建议的下一阶段不要自动开始。在启动入口、数据目录切换或 Basic runner 模板获得单独授权之前，不应声称 Basic 产品已经可以交付。

推荐顺序：

1. 增加明确的 Basic / Professional 启动入口，并在启动时设置进程级版本上下文；不要把当前单一产品默认改成 Basic。
2. 按已冻结合同实现 Basic 数据目录隔离，且不得探测或迁移 Professional 数据。
3. 为 Basic 导出提供独立的 runner 能力集，在创建临时目录和调用 PyInstaller 之前完成整份方案校验。不要把当前包含 Command / Wait 的 `EMBEDDED_TEMPLATE` 当作 Basic runner。
4. 单独审计 Professional 导出授权，这不在本阶段范围内。

在这些工作完成之前，Phase 1b 提供的是真实 Windows 适配器，以及一条默认关闭的 Basic 校验路径。
