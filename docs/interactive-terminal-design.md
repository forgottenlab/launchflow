# Interactive Terminal Mode — Future Design Only

当前 Beta 的 Command 步骤固定采用隐藏终端模式：后台运行 `cmd.exe` 或 PowerShell，等待完成，并在 LaunchFlow 内置日志中记录 stdout、stderr 和 return code。正式版与导出启动器保持一致。

本轮没有实现交互式终端，也没有使用 `start cmd`、`powershell -NoExit` 或新的步骤类型。

未来若设计“显示终端/交互式终端”，必须先明确：

- 流程是否等待终端窗口关闭，以及何时进入下一步骤；
- 是否允许键盘输入、Ctrl+C 和交互式程序；
- 显示窗口后是否仍能可靠捕获 stdout/stderr；
- 用户关闭窗口、命令退出和 LaunchFlow 退出之间的生命周期；
- 试运行与导出 EXE 如何保持相同语义；
- 安全提示、日志留存、编码和 Windows Terminal/CMD/PowerShell 的选择边界。

在这些问题形成独立设计和测试合同前，默认隐藏终端行为不得改变。
