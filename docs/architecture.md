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
4. 使用 PyInstaller 打包
5. 输出独立可执行文件

当前导出方式特点：

- 方案数据直接嵌入 EXE
- 不依赖外部 `plan.json`
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

当前项目采用“便携优先”的路径策略。

在发布版中：

- `project_root` 默认指向 exe 所在目录
- `data/`
- `licenses/`
- `logs/`

等目录都相对于程序所在位置进行管理

这样做的好处是：

- 不强依赖系统环境变量
- 更便于测试版分发
- 更易于小范围内测与本地调试

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

## 8. 后续演进方向

后续可继续考虑：

- 关于页 / 版本页
- 更完整的设置面板
- 方案导入导出
- 更丰富的步骤类型
- 更完善的日志查看器
- 更强的导出异常诊断
- 更清晰的开源仓库结构
