# Beta Testing Guide

本文档用于说明 LaunchFlow 当前 Beta 版本的测试方式、激活流程与常见问题。

---

## 1. 当前测试版本说明

当前测试版采用 **离线授权** 机制。

也就是说：

- 测试用户无需联网验证
- 程序本体可离线运行
- 授权文件绑定到当前机器
- 不同设备之间不能直接复用同一个授权文件

---

## 2. 测试用户使用流程

### 第一步：启动程序

双击打开测试版程序。

如果当前设备尚未激活，程序会自动进入激活页面。

---

### 第二步：复制申请码

在激活页中：

1. 查看当前机器码
2. 点击 **复制申请码**
3. 将申请码通过邮件发送给作者

![激活页面](images/activation-window.png)
> 当前授权生成流程以申请码为准，申请码中已经包含设备绑定信息。

当前申请码以 `LFREQ1.` 开头，自动包含客户端版本和唯一申请 ID。它使用 Base64URL 方便复制并带校验和识别文本损坏，但不是加密；申请码中不包含私钥或 license 签名。
---

### 第三步：联系作者申请授权

请将申请码发送至：

**wangheran55@gmail.com**

邮件标题建议：

```text
[LaunchFlow Beta] 申请授权
```

邮件正文建议包含：

- 你的系统版本
- 你的使用场景
- 申请码
- 你希望测试的功能点

---

### 第四步：接收授权文件

审核通过后，你将收到一个专属的授权文件，例如：

```text
TEST-0001.lic
```

---

### 第五步：导入授权文件

回到程序激活页面后：

- 点击 **导入 license 文件**
- 或直接将 `.lic` 文件拖入激活窗口

如果授权有效，状态会更新为：

```text
授权有效，可进入工作台
```

![激活成功状态页](images/activation-success.png)

此时点击 **进入工作台** 即可开始使用。

---

## 3. 授权特性说明

当前授权机制具备以下特点：

- 用户在激活页复制申请码
- 作者根据申请码生成对应 `.lic` 授权文件
- 用户在本机导入 `.lic`
- 授权文件与当前机器绑定
- 同一个 `.lic` 文件不可直接复制到其他机器使用
- 授权可设置版本标识与到期时间
- 程序启动时会自动校验授权有效性
- 私钥只保留在作者本地，永不随程序、仓库或测试包分发
- 真实 `.lic` 文件不得进入公开发布包

---

## 4. 常见问题

### Q1：为什么我不需要单独发送机器码？

因为当前申请码中已经包含设备绑定所需的机器标识信息。  
授权生成器会直接解析申请码并提取对应机器码。

---

### Q2：为什么同一个 `.lic` 文件在另一台电脑上无法使用？

这是预期行为。  
当前测试授权采用一机一授权绑定机制，授权文件只能在签发时对应的那台设备上生效。

---

### Q3：导入授权文件后仍提示无效怎么办？

请优先检查：

1. 当前导入的是否为作者发回的正确 `.lic` 文件
2. 文件是否被修改或损坏
3. 是否在与申请授权时相同的设备上导入
4. 当前授权是否已经过期

如果仍有问题，请通过邮件联系作者并附带：

- 错误提示截图

### 编辑器快捷交互

1. 分别点击“+ 网页”“+ 命令”“+ 等待”，确认新步骤立即选中且右侧属性页可直接输入。
2. 对新命令确认默认名称为“新命令”、命令为空、Shell 为 `cmd`、后续延迟为 1.0 秒。
3. 验证 `Ctrl+S`、`Ctrl+Shift+S`、`Ctrl+R`、`Ctrl+E` 与菜单提示一致。
4. 选中步骤后按 `Delete`，确认使用与删除按钮相同的确认流程。
5. 执行一个不可用命令，确认日志同时保留原始输出/退出码并显示用户提示；Windows 9009 应解释为命令未安装或未加入 `PATH`。
6. 修改当前步骤后直接按 `Ctrl+S`，重新加载 JSON，确认无需点击“保存此步骤修改”且 Command 的引号、换行、`%` 与中文未改变。
7. 修改步骤后直接切换到另一项，确认旧步骤自动提交；编辑器加载新步骤时不应产生额外保存或列表闪烁。
8. 在有效 Application 后添加空 Command，点击试运行或导出，确认 Application 尚未启动、worker 未创建，并自动选中/聚焦空命令字段。
9. 启动 XMind 等 Electron GUI 应用，确认开发 PowerShell 不出现应用 stdout/stderr；Application 应立即返回，Command 输出仍进入 LaunchFlow 日志。
10. 创建三个步骤并拖动第三项到最上方，确认保存、试运行和导出快照都使用新顺序，步骤参数与 ID 不变。
11. 步骤列表聚焦时验证 `Alt+↑` / `Alt+↓`；命令输入框聚焦时同一按键不得移动步骤。
12. 检查保存、运行、导出和删除 tooltip 与菜单快捷键一致；Command/Shell tooltip 应说明后台执行且不弹外部终端。
13. 打开“反馈问题”，检查诊断预览后再复制；它不会自动上传，发送前仍需人工检查命令和文件路径。

正式发布版和导出启动器的 Command 都默认隐藏 CMD/PowerShell/Windows Terminal，stdout、stderr 和退出码统一进入 LaunchFlow 日志。交互式终端是未来独立设计，不属于当前 Beta。

### 开发者人工授权测试

1. 使用管理员端 `issue-dev` 为本机申请码签发一次 developer license；必须显式提供私钥位置，不在客户端执行签名。
2. 将结果明确输出到 `%LOCALAPPDATA%\LaunchFlow-Dev\licenses\license.lic`。
3. 从 source 目录或其他 cwd 调用 `tools/run_editor_dev.ps1`，确认数据只进入 `LaunchFlow-Dev`。
4. 有效 developer license 应直接进入工作台；缺失 license 应进入激活页；伪造、过期或其他机器的 developer license 必须被拒绝。
5. 关闭程序后确认当前 shell 原有 `LAUNCHFLOW_DATA_DIR` 未被永久修改。

自动化 smoke 不使用真实 developer license 或正式私钥；它创建临时签名链和临时数据根并在结束后删除。
- 当前系统版本
- 你导入的授权文件名
- 激活页截图

---

### Q4：测试版是否支持导出 EXE？

支持。导出功能会尝试使用本机可用的 PyInstaller 构建器：

- 开发版优先使用当前 Python 环境中的 PyInstaller
- 发布版会尝试使用系统 `PATH` 中的 `pyinstaller`、`python -m PyInstaller` 或 `py -m PyInstaller`

导出用户启动包时，本地应用步骤中的 `.exe`、`.bat`、`.cmd`、`.com`、`.ps1` 文件会自动随包携带。

不建议将 `.lnk` 快捷方式作为可分发资产，因为它通常依赖当前机器上的绝对路径。

如果目标应用依赖外部 DLL、配置文件或数据目录，目标电脑仍需要具备对应环境。当前导出只携带启动文件本身，不自动复制完整安装目录或依赖树。

---

## 5. 当前验证状态

已验证：

- Python 文件语法结构检查通过
- 导出资产收集逻辑会生成 `_embedded_asset`，且不会修改原始 plan
- 最小真实 PyInstaller 导出 smoke 通过
- smoke 中 `.cmd` 与 `.ps1` 均从 `_MEI.../launchflow_assets/` 执行
- GUI smoke 通过：主窗口可实例化，等待/延迟秒数控件可找到，等待秒数上下按钮可通过 QtTest 点击
- 发布版 smoke 已完成一次通过：`dist/LaunchFlow.exe` 可构建，发布目录未发现私钥或真实 `.lic`，短启动可进入激活流程
- `git diff --check` 无空白错误

未覆盖或仍需人工确认：

- 不同用户机器上的发布版内导出，取决于本机是否安装 PyInstaller 或可用 Python 环境
- 重新构建发布版前需要确认没有遗留运行中的 `dist/LaunchFlow.exe`
- 复杂第三方应用的 DLL、配置目录、插件目录和数据目录不会被自动复制
- UI 视觉细节仍建议在真实 Windows 桌面环境下按 [GUI Smoke Checklist](gui-smoke-checklist.md) 人工点击确认
- 有效 `.lic` 导入后的完整工作台进入路径仍需使用测试授权文件人工验证

---

## 6. 测试反馈建议

如果你愿意帮助改进 LaunchFlow，欢迎反馈以下内容：

- UI 体验问题
- 试运行异常
- 导出异常
- 授权流程问题
- 日志显示问题
- 主题切换问题
- Windows 兼容性问题

建议反馈时附带：

- 截图
- 错误文本
- 操作步骤
- 系统版本

---

## 7. 2026-07-10 自动验证补充

已验证：

- Command capture smoke 通过，覆盖 `python --version`、不存在命令、中文输出、带空格/中文路径和 Windows 无窗口创建参数。
- 深色/浅色 offscreen GUI smoke 通过，4 个 SpinBox 的上下点击有效，Shell ComboBox 的文本区、箭头区与箭头左侧均能展开。
- Release smoke 在完整 Conda 环境中真实构建并短启动 `LaunchFlow.exe`，构建日志确认复制 ICO，发布目录未发现私钥或 `.lic`。
- Export smoke 真实构建并运行，cmd/ps1 应用资产来自 `_MEI.../launchflow_assets`，cmd/PowerShell Command 步骤均完成，原 plan 未修改。
- `vol C:` 管道回归通过；Command runner 对 stdout/stderr 大输出使用 `communicate()` 完整读取，延迟命令结束前 worker 不释放，无残留 `cmd.exe`。
- LFREQ1 请求码和作者 Admin CLI smoke 通过；临时 RSA 测试密钥仅存在系统 TEMP 并在测试结束后删除，未使用正式私钥或生成正式用户 license。

### 用户数据与备份

- 用户只需保存 `LaunchFlow.exe`；可变数据默认位于 `%LOCALAPPDATA%\LaunchFlow`，不会在桌面或 EXE 同目录创建运行目录。
- `AppData` 默认隐藏，可在资源管理器地址栏直接输入 `%LOCALAPPDATA%\LaunchFlow`。
- 建议备份 `plans/` 和 `licenses/`。卸载或删除 EXE 不会自动删除用户数据，彻底卸载需在确认备份后手动删除 `LaunchFlow` 数据目录。
- 导入的 license 会复制为固定的 `licenses/license.lic`，后续不依赖原文件；不要随意手工编辑该文件。
- 新方案默认保存到 `plans/`，但“另存为”和导出 EXE 的目标位置仍由用户自行选择。
- 旧版数据迁移只复制、不覆盖、不删除。确认新目录内容正确前，请保留旧文件；之后由用户自行决定是否删除。
- 自动截图使用项目 palette/style 的离屏模拟主题，只能证明窗口、SpinBox 与 ComboBox 成功渲染，不能替代真实 Windows 主题、字体、DPI 和美观判断。

仍需人工确认：

- SpinBox 和 ComboBox 箭头在真实 Windows 深色/浅色桌面中的肉眼效果。
- 100%、125%、150% DPI 下的真实布局、hover、pressed、disabled 视觉。
- 任务栏图标、窗口图标与 Windows 图标缓存刷新后的最终显示。

---

## 8. 2026-07-15 编辑器工作区体验补充

已通过自动验证：

- source/frozen 图标路径、QApplication/MainWindow/ActivationWindow 图标和 QApplication 前 AppUserModelID 调用顺序。
- 历史方案单击仅载入一次、Enter 载入、方向键只选择，以及 dirty 状态下保存/放弃/取消。
- 拖拽首尾扩展投放区、上/下半区索引、半透明缩放预览、主题化插入指示器和 step ID 恢复。
- 日志七类格式、深浅主题重着色、纯文本复制/诊断/磁盘兼容、滚动保护、4000 blocks 上限和 UI-only 清空。
- Release onefile 48,967,840 bytes、数据隔离和 Export onefile 8,591,684 bytes 真实通过。

仍需人工确认：源码/发布版任务栏图标和 Windows 图标缓存；鼠标拖拽手感及 auto-scroll；深浅主题、100%/125%/150% DPI；日志三态布局与右侧工具栏的真实视觉。

正式版 Command 继续后台无窗口运行，stdout、stderr 和退出码进入内置日志；本轮没有实现交互式终端或新步骤类型。

### 拖拽、日志与控件边框修复

- 新增拖拽生命周期 smoke：连续 20 次让 Qt item 包装对象在 `QDrag.exec()` 内失效，确认结束代码不再访问旧 item，cancel、dragLeave、drop 后状态均清除，步骤数量、ID 与选择不变。
- ghost card 变为更窄的单卡片预览，不再叠加第二层蓝色外框；源位置仅保留虚线占位。插入提示保留全宽 4px 线、左箭头与最终位置文本，但文本位于右侧，不遮挡左侧步骤名称。
- 日志标题行集中标题、状态、未读提示和紧凑显隐/恢复入口；右侧固定五个无外层框工具按钮。collapsed 全隐藏，空间不足时只显示放大按钮，极小时右侧整体隐藏但标题行始终提供“恢复高度”。
- 浅色/深色主题输入边框覆盖 LineEdit、TextEdit/PlainTextEdit、ComboBox、DoubleSpinBox/SpinBox；顶部栏背景与垂直对齐新增三档 scale factor 自动检查。
- SpinBox 上下按钮在 Qt 100%、125%、150% scale factor 下自动断言同宽同高，并继续验证边框、分隔线、箭头与增减命中区。
- ComboBox/DoubleSpinBox 的完整外框、右侧分隔区、箭头和 SpinBox 中线已在深浅主题以及 Qt 100%/125%/150% scale factor 下完成渲染与 hitbox 自动验证。
- 自动验证不能替代真实 Windows 鼠标拖拽、系统主题、字体和物理 DPI 肉眼验收；新增人工清单仍保持 Pending。
- 本轮最终 onefile 闭环通过：Release `LaunchFlow.exe` 48,973,995 bytes，桌面隔离目录仅含 EXE；Export 启动器 8,591,361 bytes，启动器目录零污染。

### 2026-07-15 UI mature polish follow-up

- 18 项源码/UI smoke 全部通过；新增 `check_topbar_alignment_smoke.py`，并扩展拖拽、日志、字段边框和 SpinBox 测试。
- 当前源码 Release onefile 为 48,974,555 bytes；沙箱外 frozen probe 创建全部隔离目录并保持激活窗口存活。
- Release data isolation 的桌面模拟目录仅包含 `LaunchFlow.exe`；Export onefile 为 8,592,281 bytes，cmd/PowerShell 资源来自 `_MEI`，launcher directory pollution 为 none。
- 仍需真实 Windows 中文字体、物理鼠标、系统主题与 100%/125%/150% DPI 肉眼确认；自动截图中的方框字形是 offscreen 字体限制。

## 9. 双语项目文档与截图

- `README.md` 是完整简体中文入口，`README_EN.md` 是独立英文入口；两者均在首行区域提供语言切换。
- 文档明确区分已验证检查点 `v0.1.0-beta.2` 与程序内部版本 `0.1.0-beta`，不把 Beta 描述为稳定版。
- 六张公开截图由 `tools/generate_readme_screenshots.py` 实例化正式窗口和控件生成，使用隔离数据目录且不读取或创建许可证。
- `tools/check_readme_docs_smoke.py` 检查截图尺寸与唯一性、双语引用、本地链接、公开路径、敏感请求内容和残留占位文案。
- 截图脚本使用真实 Windows 中文字体渲染；它用于可重复文档采集，不替代物理鼠标、键盘、系统主题和打包 EXE 验证。

验证命令：

```powershell
python tools/generate_readme_screenshots.py
python tools/check_readme_docs_smoke.py
```

## 10. 免责声明

当前版本仍属于 Beta 测试版。

这意味着：

- 功能可能继续调整
- 部分行为可能尚未完全稳定
- 文档可能仍在迭代更新

请勿将测试版用于关键生产环境。
