# Myink n8n 集成

这个工作流把 Myink 的长篇创作链路接到 n8n：

`登录 → 创建作品 → 设定草稿/确认 → 大纲草稿/确认 → 批量生成 → 轮询任务 → 逐章取正文 → 导出 Markdown`

n8n 只负责编排和调用 Myink API，真正的多 Agent 推理、记忆和校验仍在 Myink 服务内完成。它不是把 Python 服务搬进 n8n。

## 导入

- 在 n8n 中打开 `Integrations` / 工作流导入，选择 `myink-pipeline.json`。
- 或调用 n8n 公共 API：`POST /api/v1/workflows`，请求体为文件内容。

## 首次运行

打开 `配置` 节点填写：

| 字段 | 说明 |
|---|---|
| `baseUrl` | Myink 地址，例如 `https://myink.cloud`，不要以 `/` 结尾 |
| `username` / `password` | Myink 账号；工作流暂不支持 MFA 账号 |
| `title` / `genre` / `premise` / `storyline` | 新书参数 |
| `chapterCount` | 长篇大纲至少 50 章，默认 50 |
| `batchSize` | 本轮生成章数，默认 2 |
| `waitSeconds` | 轮询间隔，默认 30 秒 |
| `outputDir` | 成稿保存目录，默认 `/Users/a1/.n8n-files`（n8n 默认只允许写 `~/.n8n-files`） |

运行前确认 Myink 已配置可用的模型连接，且账号有建书和生成额度。

## 输出

- 成功后在 n8n 执行结果里返回 `projectId`、章节数、字数和文件路径。
- 成稿写到运行 n8n 的机器：`<outputDir>/myink-<projectId>.md`，默认 `/Users/a1/.n8n-files/myink-<projectId>.md`。
- `awaiting_review`、`awaiting_plan`、`paused` 会终止工作流，需要到 Myink 页面人工处理后另行续跑。

## 安全

`配置` 节点会把账号密码保存在 n8n 工作流数据中。建议使用专用账号、限制 Myink 访问范围，并在使用后轮换密码。更严格的环境应把登录节点改成 n8n 的 Header Auth 凭证，或由外部密钥管理注入短期 token。
