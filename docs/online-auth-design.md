# LaunchFlow Online Authentication Design

## 1. Status and scope

当前 Beta 不实现在线账号系统、后端服务或自动签发。本设计仅描述未来可能采用的 Device Authorization Flow。现阶段继续使用：

- 正式用户：签名、机器绑定、有期限的用户 license。
- 开发者人工测试：签名、机器绑定、有期限的 `edition=developer` license。
- 自动化测试：隔离临时目录、临时测试密钥和临时测试 license，测试完成后删除。

## 2. Device Authorization Flow

1. 客户端通过 TLS 请求短期 `device_code`、用户可输入的 `user_code`、验证网址和轮询间隔。
2. 客户端显示验证网址与用户码，不在桌面程序中收集账号密码。
3. 用户在系统浏览器中登录并确认设备授权。
4. 客户端按服务端规定的间隔轮询授权状态，并处理 pending、slow-down、expired、denied 等状态。
5. 授权成功后，服务端返回短期 access token 和由服务端私钥签名的 entitlement token。
6. 客户端使用内置公钥校验 entitlement 的签名、产品、设备、权限、签发时间和有效期。
7. entitlement 缓存到 LaunchFlow AppData；缓存内容不得包含服务端私钥。
8. 网络不可用时只允许有限离线宽限期，超过宽限期必须重新在线确认。
9. refresh token 存入 Windows Credential Manager，不写入普通 JSON、日志、方案文件或 `.ai/`。
10. 服务端签名私钥只存在于受控服务端密钥系统，永不进入客户端、安装包或源码仓库。

## 3. Required backend capabilities

- 账号注册、登录、找回、MFA 与会话撤销。
- device-code 生命周期、轮询限速、重放保护和用户确认页。
- entitlement 签发、密钥轮换、撤销列表与审计。
- 数据库迁移、备份、灾难恢复和服务可用性监控。
- 隐私政策、数据保留/删除规则和安全事件响应。
- 客户端时钟偏差、离线宽限期和服务故障降级策略。

## 4. Security boundaries

- Build channel、命令行参数或普通环境变量都不得跳过签名校验。
- entitlement 不能只依赖“登录成功”布尔值；客户端必须校验服务端签名和有效期。
- refresh token 不得写入 `settings.json`、license 文件、日志或崩溃报告。
- 邮件到达后完全自动签发不适合当前阶段；邮件自动化最多进入待审核队列并生成回复草稿，签发仍需人工批准。
- 在线授权不能削弱现有离线 license 的 RSA 验签、机器绑定和过期检查。

## 5. Adoption prerequisites

在实现前必须单独完成威胁模型、API 协议、后端部署、数据库设计、Credential Manager 集成、隐私文本、密钥轮换和故障演练。完成这些前，不应把当前 Beta 的 developer/user license 流程替换为在线登录。
