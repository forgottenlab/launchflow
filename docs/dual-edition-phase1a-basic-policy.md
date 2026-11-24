# LaunchFlow 双版本架构 — Phase 1a Basic 策略核心

- 状态：Phase 1a 已实现可复用、无副作用的 Basic 方案校验核心；尚未接入生产入口
- 日期：2026-11-23（Asia/Shanghai）
- 生产模块：`shared/basic_policy.py`
- 测试：`tools/check_basic_policy_phase1a_smoke.py`
- 上游合同：`docs/dual-edition-phase0-contract.md`（含 Phase 1a 附录）

本文记录已经实现的 Phase 1a 行为，并明确尚未完成的接入工作。不得把下文“已知限制”或“Phase 1b 要求”写成已经交付的产品能力。

Phase 1a **没有**修改 GUI、运行时执行器、应用启动实现、许可/HWID、方案 schema、Professional 执行或导出器，也没有实现真实 Windows LNK 解析或驱动器分类适配器，没有调用 PyInstaller，没有开始 Phase 1b。

---

## 1. 模块架构

`shared/basic_policy.py` 是一个独立的生产模块，位于 `shared/` 下，不修改 `shared/models.py`、`shared/plan_schema.py` 或 `shared/platform/`。

它只依赖：

- Python 标准库
- `shared.models.Plan`（用于已构建模型的入口）

它不导入 `editor/`、`runtime/`、`licensing/`、`tools/` 或 `shared.platform`。现有编辑器、运行时和导出路径不会加载该模块。

依赖通过构造函数式参数注入，避免策略核心直接探测文件系统、盘符类型或操作系统快捷方式：

| 接口 | 职责 | Phase 1a 适配器 |
| --- | --- | --- |
| `FilesystemInspector` | 查询路径是否存在、是否为目录 | 仅由测试提供合成实现 |
| `DriveClassifier` | 判断路径所在驱动器是本地、远程、未知或不可用 | 仅由测试提供合成实现 |
| `ShortcutResolver` | 解析快捷方式的真实目标、类型与参数 | 仅由测试提供合成实现 |

缺少这些依赖、依赖抛出异常，或返回无法判定的结果时，策略失败关闭（fail closed），不会回退到盲目打开快捷方式，也不会把盘符路径自动当成本地路径。

---

## 2. 公共校验接口

### 2.1 `validate_basic_plan_document(document, *, filesystem, drive_classifier, shortcut_resolver, dependencies) -> BasicPolicyResult`

原始方案文档入口。接受 JSON 反序列化后的映射对象。

必须在调用 `plan_from_dict()` 或其他会丢弃未知字段的模型构造之前使用。根对象或步骤中的未知字段会被直接报告，输入文档不会被改写。

若误传入已经构造好的 `Plan` 对象，会转到 `validate_basic_plan()`。此时无法再看到已经被模型层丢掉的未知字段。

### 2.2 `validate_basic_plan(plan, *, ...) -> BasicPolicyResult`

已有 `Plan` 对象入口。通过 `plan.to_dict()` 读取字段快照并校验，不修改原对象。

该入口看不到先前反序列化已经静默丢弃的未知根字段。JSON 载入路径必须先走文档入口。

### 2.3 依赖对象

`BasicPolicyDependencies` 可一次性注入上述三个接口。关键字参数优先于该对象中的同名依赖。

`ShortcutResolver` 既可以是带 `resolve_shortcut()` 的对象，也可以是 `path -> ShortcutResolution | mapping | None` 的可调用对象。映射形式兼容 Phase 0 合成 oracle 的字段名（`target` / `target_path`、`arguments`、`working_dir` / `working_directory`、`target_kind`、`status`）。

---

## 3. 结构化错误结果

结果类型为不可变数据类：

- `BasicPolicyResult.accepted`：仅当整份方案没有任何问题时为 `True`
- `BasicPolicyResult.issues`：确定性顺序的 `BasicPolicyIssue` 元组
- `BasicPolicyIssue.code`：稳定错误码
- `BasicPolicyIssue.path`：字段路径，例如 `edition`、`steps[0].delay_after`
- `BasicPolicyIssue.step_index`：从 0 开始的步骤下标；根级问题为 `None`

任何不受支持的步骤都会使 `accepted=False`。校验器不会删除步骤、改写延迟，或对输入做兼容降级。

常用错误码：

| 错误码 | 含义 |
| --- | --- |
| `unknown_plan_fields` / `unknown_step_fields` | 未知字段 |
| `basic_unsupported_step_type` | Command / Wait / 未知类型，含禁用步骤 |
| `basic_incompatible_delay` | 已给出的延迟不是精确的数值 1 / 1.0 |
| `basic_custom_arguments_forbidden` | 非空应用参数 |
| `basic_custom_working_dir_forbidden` | 非空工作目录 |
| `basic_custom_browser_forbidden` | 自定义浏览器 |
| `basic_custom_start_minimized_forbidden` | 非默认最小化启动 |
| `basic_network_target_forbidden` | UNC 或 URL 形式的应用路径 |
| `basic_mapped_or_remote_drive_forbidden` | 注入分类器判定为远程/映射盘 |
| `basic_drive_locality_unknown` | 盘符本地性未知或分类不可用 |
| `basic_relative_path_forbidden` | 相对路径或盘符相对路径 |
| `basic_device_path_forbidden` | 设备路径（如 `\\.\` / `\\?\`） |
| `basic_unsupported_path` | 其他不受支持的路径表示 |
| `basic_target_missing` | 目标不存在 |
| `basic_filesystem_unavailable` | 无法确认存在性，失败关闭 |
| `basic_script_or_unsupported_target` | 脚本或非普通本地 EXE（含 `.com`） |
| `basic_lnk_resolver_required` | 缺少快捷方式解析器 |
| `basic_lnk_resolver_error` | 解析器异常 |
| `basic_invalid_lnk` | 无法解析为本地 EXE |
| `basic_lnk_arguments_forbidden` | 快捷方式带参数 |
| `basic_lnk_network_target_forbidden` | 快捷方式指向网络目标 |
| `basic_lnk_unsupported_target_kind` / `basic_lnk_non_exe_target` | 快捷方式目标不是已存在的本地 EXE |
| `basic_unsupported_url_scheme` | 非 HTTP/HTTPS，或缺少 netloc |

---

## 4. 原始 JSON 校验边界

现有 `shared/models.py` 中的 `plan_from_dict()` 只读取 `plan_name`、`version`、`steps`，因此根级未知字段（例如夹具中的 `edition`）会被模型层丢弃。步骤构造使用 `AppStep(**data)` 等形式，未知步骤字段通常会抛出 `TypeError`，而不是变成结构化拒绝。

`shared/plan_schema.py` 的 `validate_plan_dict()` 只做轻量结构检查，不拒绝未知字段。Phase 1a **没有修改**这两个现有模块。

Basic 的未知字段检测必须发生在模型反序列化之前，入口是 `validate_basic_plan_document()`。允许字段完全来自现有模型与已冻结合同，没有新增 schema，也没有增加 `edition` 字段：

- 根：`plan_name`、`version`、`steps`
- 步骤公共字段：`id`、`type`、`name`、`enabled`、`delay_after`
- App：`path`、`args`、`working_dir`、`start_minimized`
- URL：`url`、`browser_path`

未知值、错误类型和不支持的表示一律失败关闭，不会被静默改写。

---

## 5. 校验语义摘要

### 5.1 EXE

只接受词法上合法的 Windows 盘符绝对路径，后缀必须是普通 `.exe`（大小写不敏感）。目标必须经注入的文件系统确认存在且不是目录，并经注入的分类器确认为本地驱动器。

拒绝：相对路径、盘符相对路径（如 `C:Editor.exe`）、UNC、URL 形式路径、设备路径、含保留设备名或非法字符的表示、脚本与 `.com`、不存在的目标、远程或无法确认本地性的驱动器。

路径语法使用显式 Windows 规则（分隔符、UNC、设备前缀、盘符绝对路径），不使用宿主操作系统默认的 `pathlib.Path` 来判断绝对或相对。

### 5.2 LNK

快捷方式位置本身必须通过与 EXE 相同的本地性、存在性和路径语法检查，并且后缀为快捷方式扩展名。然后必须通过注入的解析器得到真实目标。

成功条件：目标是已存在的本地 EXE；快捷方式参数为空；快捷方式工作目录为空；不是网络目标；目标类型为 `executable`。

缺少解析器、解析器抛错、返回无法识别的结果或 `status != "resolved"`，一律失败关闭。策略不会回退到未校验的 shell 打开，也不会仅因扩展名是快捷方式就接受它。

Phase 1a **没有**实现 Windows COM、ShellLink 或真实操作系统快捷方式解析。

### 5.3 URL

只接受 `http` 与 `https`，并且 `urlparse` 后必须有 netloc。非空 `browser_path` 会被拒绝。缺失延迟视为允许的默认 1 秒。

### 5.4 Delay

Basic 要求精确的 1 秒。

- 接受数值 `1` 与 `1.0`
- 字段缺失时沿用现有模型默认 `1.0`，因此允许
- 明确拒绝：布尔值（`True == 1` 不得绕过）、`0`、其他数值、负数、NaN、Infinity、字符串 `"1.0"` 以及其它非数值类型
- 不使用近似浮点容差

### 5.5 禁用步骤

`enabled=false` 不会跳过校验。禁用的 Command / Wait / 其他不受支持步骤会使整份方案被拒绝。合法步骤之后出现不受支持步骤同样整份拒绝。

### 5.6 未知字段

根或步骤中的未知字段使整份方案被拒绝。校验过程不调用 `plan_from_dict()`，也不会从输入文档中删除这些字段。

### 5.7 映射网络驱动器

`Z:\Apps\example.exe` 这类盘符路径不会仅因词法形式就被当成本地路径。必须询问注入的 `DriveClassifier`：

- `local`：在其他检查通过时可接受
- `remote`：拒绝（`basic_mapped_or_remote_drive_forbidden`）
- `unknown` / `unavailable` / 缺少分类器 / 分类器异常：失败关闭（`basic_drive_locality_unknown`）

Phase 1a **没有**实现真实 Windows 驱动器类型适配器。词法检查仍负责拒绝 UNC 与 URL 形式路径，但不能单独发现映射盘。

---

## 6. 副作用限制

策略核心不得：

- 执行应用程序或打开 URL
- 启动子进程
- 写入文件或修改环境变量
- 读取机器身份、许可状态、AppData 或私钥
- 发起网络请求
- 调用现有 `RuntimeExecutor`
- 调用 PyInstaller 或现有导出器
- 在未注入依赖时自行访问操作系统快捷方式或盘符类型 API

测试只使用合成路径、合成夹具和伪造的依赖实现。

---

## 7. 测试覆盖

`tools/check_basic_policy_phase1a_smoke.py` 使用现有 Phase 0 合成夹具，不替换这些夹具，也不读取真实用户方案。覆盖包括：

1. 全部 8 个 Basic 合法夹具通过
2. 全部 17 个 Basic 非法夹具被拒绝
3. 7 个 Professional 兼容夹具不会被误当作 Basic 接受
4. 禁用的不受支持步骤被拒绝
5. 合法步骤之后的不受支持步骤仍使整份方案被拒绝
6. 未知原始 JSON 字段在模型反序列化前被拒绝，且不调用 `plan_from_dict()`
7. 布尔延迟被拒绝
8. 精确整数/浮点 1 秒被接受；缺省延迟被接受
9. 其他数值与非有限数值被拒绝
10. UNC 路径被拒绝
11. 注入的远程盘分类被拒绝
12. 未知或不可用的盘分类失败关闭
13. 本地盘分类可以通过
14. 缺少 LNK 解析器失败关闭
15. 解析器异常失败关闭
16. 带参数的 LNK 被拒绝
17. 指向脚本的 LNK 被拒绝
18. 指向网络位置的 LNK 被拒绝
19. 合法的合成本地 EXE LNK 通过
20. 校验不修改输入方案

现有 Phase 0 合同冒烟测试 `tools/check_dual_edition_contract_smoke.py` 必须继续通过。Phase 0 测试专用模块仍然没有接入生产入口；Phase 1a 只新增了一个尚未接线的 `shared/` 模块。

---

## 8. 已知限制

- 没有真实 Windows LNK 解析器。生产接入前必须在 Phase 1b 提供基于操作系统的解析适配器，并继续失败关闭。
- 没有真实 Windows 驱动器分类适配器。没有注入分类器时，盘符绝对路径不能被接受。
- 本模块尚未接入方案加载、GUI 预检、试运行、运行时执行器或导出预检。当前产品行为仍是 Phase 0 记录的 Professional / 单一产品行为。
- 本模块不改变 Professional 对 LNK 的现有 `shell_open` 行为。
- 本模块不实现 Basic 数据目录切换，也不读取或迁移 Professional 数据。
- 词法路径检查不能发现映射网络驱动器。

---

## 9. Phase 1b 接入要求

建议的下一阶段仅限于接入，不要自动开始：

1. 实现真实 Windows 快捷方式解析适配器（例如 IShellLink / COM），输出本模块需要的目标路径、类型与参数；解析失败必须失败关闭。
2. 实现真实 Windows 驱动器/路径分类适配器，识别映射网络驱动器与其他远程卷。
3. 在所有方案入口接入 `validate_basic_plan_document()`：直接 JSON 加载、导入、模板、历史、禁用步骤、直接模型/执行器调用、导出。校验必须发生在任何执行或打包副作用之前。
4. 在接入时保持 Professional 现有行为、现有合法方案、离线许可和当前导出授权行为不变。Professional 导出授权的单独审计仍待后续任务。
5. 不要在 Phase 1b 之前修改 `EMBEDDED_TEMPLATE`、切换数据目录或引入 Basic/Professional 启动入口，除非有新的明确授权。

---

## 10. 验收标准

Phase 1a 完成的标准是：Basic 策略核心能够独立、确定地接受每一个合法 Basic 合成方案，拒绝每一个非法 Basic 合成方案，通过注入的分类器拒绝映射网络驱动器，并在不修改现有 Professional 生产行为的前提下执行整份方案校验合同。

---

## 附录：Phase 1b 追加说明（2026-11-24，Asia/Shanghai）

以下内容不改写上文已记录的 Phase 1a 行为，只补充后续已实现事项：

- Phase 1b 已新增真实 Windows 快捷方式解析适配器（IShellLink / COM）和盘符分类适配器（GetVolumePathNameW / GetDriveTypeW）。映射网络驱动器及其他远程卷通过分类器拒绝；词法检查仍不能单独发现映射盘。
- alidate_basic_plan_document() 已通过 shared/edition_policy.py 以门控方式接到方案加载、模板、预检、执行器和导出入口。只有显式 Basic 版本上下文处于活动状态时才会强制校验。当前产品默认上下文未设置，Professional / 单一产品行为保持不变。
- Phase 1b **没有**修改 EMBEDDED_TEMPLATE、数据目录身份、启动入口、许可或导出授权。Professional 导出授权仍待后续单独审计。
- 详见 docs/dual-edition-phase1b-windows-adapters.md。
