"""
app_info.py

项目统一元信息模块。

该模块集中维护应用名称、版本、作者、联系邮箱等信息，
用于减少多个模块中的重复硬编码，并为后续 README、关于页、
打包信息以及文档说明提供统一数据来源。

位置：
- shared/app_info.py

注意事项：
- 仓库地址在项目公开前可以留空。
- 如需在界面或文档中显示版本信息，优先从本模块读取。
"""

APP_NAME = "LaunchFlow"
APP_VERSION = "0.1.0-beta"
APP_AUTHOR = "你的名字"
APP_EMAIL = "wangheran55@gmail.com"
APP_REPOSITORY = ""
APP_DESCRIPTION = "一个面向 Windows 的可视化启动流程编排工具。"