# 账号、密码与写作隔离

## 使用方式

登录页可用用户名和密码登录；注册新账号还必须提交有效邀请码。用户名为 3–64 位 ASCII 字母、数字、下划线或短横线，去除首尾空白并转小写；新密码为 8–128 个 Unicode 字符，并至少包含 1 个 ASCII 字母和 1 个 ASCII 数字。不要求大小写混合或特殊符号，允许符号，不裁剪空白。密码使用随机盐和 scrypt（N=131072、r=8、p=1）存储，不保存明文。旧密码哈希仍可登录，但下次设置新密码时必须满足新规则。

邀请码由服务器操作员发放，默认 7 天后过期且只可成功注册一次。服务端只存 SHA-256 摘要，明文只在创建命令的标准输出中显示一次。核销与创建账号处于同一数据库事务；重名或建号失败会回滚核销。

```bash
myink create-invite
myink create-invite --expires-days 14 --max-redemptions 1
myink revoke-invite <invitation-id>
```

账号页可修改密码；改密需要当前密码。退出和改密都会撤销**该账号所有设备**的现有会话。登录凭证过期后需重新登录。不提供邮箱验证码或公开找回密码接口；本机管理员可以交互式重设密码，命令行参数不包含密码。

如果退出时网络不可用，浏览器会提示仅完成本机退出；服务端未能确认撤销的凭证仍可能在原有效期内使用。正常连接下的成功退出会撤销全部会话。

```bash
myink reset-password demo
# 容器部署：docker compose exec myink-api myink reset-password demo
myink set-role demo admin
myink set-role demo user
```

旧账号与示例书保留原 user_id 和归属，但旧账号没有默认密码；必须由管理员重设后才能登录。注册新账号不会领取 demo 的书籍或环境配置。

## 首次配置与无损升级

1. 先备份已有数据库和配置。保留原 `.env`，不要复制样例覆盖它。
2. 新安装设置独立、稳定的 `MODEL_CREDENTIAL_KEY`，并设置强随机 `JWT_SECRET`（至少 32 字节，建议 `openssl rand -base64 48`）。Python 与 Go 必须使用同一 JWT 密钥。所有环境都拒绝默认或过短的 JWT 密钥，返回 `AUTH_SECRET_NOT_CONFIGURED`。
3. 已有模型密文且未独立设置 `MODEL_CREDENTIAL_KEY` 时，先将原有效 `JWT_SECRET` 固定到 `MODEL_CREDENTIAL_KEY`，确认旧密文仍可解密，再更换 JWT 密钥。若历史环境使用过源码中的开发默认值，按旧配置确定有效派生密钥，不要把实际密钥写入文档或提交；公网部署前需完成密钥轮换与存量密文迁移。
4. 使用新版本执行 `myink auth-upgrade`，仅添加密码字段、会话版本、规范用户名唯一索引以及默认为 `user` 的角色列。重复执行安全，不修改用户名或作品。如果旧用户名经去空白/小写后冲突，升级会回滚并报错，不自动合并或删除账号。`myink init` 也包含该升级，并已取消自动删除遗留表/列的步骤；它默认不创建 demo 账号与示例书，需要开发示例数据时用 `myink init --seed`。
5. 管理员使用 `myink reset-password <username>` 为旧账号设置密码；新用户自行注册。部署时协调重启 API、网关和 worker，旧格式 JWT 不再接受。既有队列中没有合法用户归属的消息会被拒绝，不猜测归属。

本次实现不会自动修改现有 `.env`、轮换密钥、删除书籍或运行开发库迁移。

## 隔离边界

- Caddy 是唯一用户入口，只发布 80/443；Go 网关与 Python API 都只在容器网络内监听。身份由 Python 自己验 JWT（HS256 + 签发方 + 必需声明 + 会话版本比对），客户端伪造 `X-Myink-User` 已完全无效——Python 不读这个头。
- 注册、登录和改密共享每个来源地址每分钟 20 次限额；认证请求体最多 4096 字节，密码计算每个 API 进程最多并发 2 次。来源地址取自 Caddy 覆盖写入的 `X-Myink-Client-IP`，客户端伪造同名头会被抹掉。
- Python 业务接口只在容器网络内开放（`expose`，不发布宿主机端口）；**不要单独公开 Python 8100 端口**——它自己验签，但绕过 Caddy 就同时绕过了 TLS 与限流。数据库、Redis 和 RabbitMQ 同样不能面向不可信网络。
- `role=user|admin` 是管理权限，与 `tier=normal|vip` 任务优先级完全独立。管理员依赖完整 Bearer 验签、会话版本和数据库当前角色；不信任 `X-Myink-User`、JWT 角色宣称或浏览器存储。修改角色会撤销该账号的旧会话。管理员可查看用户写作与调试内容，注册页已明示提醒。
- 项目、章节、候选、记忆、历史及用户环境先校验归属；项目内容受 PostgreSQL FORCE RLS 和事务级租户上下文保护。应用数据库角色必须是 `NOBYPASSRLS`，不能使用超级用户作为业务连接。
- 任务详情、暂停/继续/取消/确认计划、入队与 SSE 都验证书籍归属；尚未落库的任务使用入队时预先记录的归属。worker 在执行前再次验证用户、书籍和任务关联，拒绝伪造消息；暂时数据库故障重新入队而不是丢弃任务。
- SSE 按 JWT 到期时间停止发送，每 15 秒检查会话，检查超时 5 秒，撤销通常在最多约 20 秒内停止发送；空闲连接关闭还可能等待 Redis 阻塞读取返回。因此不是零延迟全连接撤销。
- 浏览器会话变更会卸载旧账号页面、关闭实时订阅并隔离写作本地状态；浏览器本地存储不是抵御同一操作系统用户、开发者工具或 XSS 的安全边界。共用设备须退出并妥善保护浏览器资料。

## API

对外只有一个前缀 `/api/v1`，契约见 `spec/api-openapi.json`。Caddy 按路径把 `/api/v1/tasks/*/events` 分给 Go 网关（SSE 中继），其余 `/api/v1/*` 与 `/healthz` `/readyz` 分给 Python；非 `/api/v1` 的 `/api/*` 直接回 JSON 404，不会落进 SPA 回退。

| 方法与路径 | 请求 | 结果 |
|---|---|---|
| POST `/auth/register` | username、password、invitation_code | 201，token/user_id/username/tier/role/expires_in |
| POST `/auth/token` | username、password | 200，同上 |
| GET `/auth/session` | Bearer token | 当前 user_id/username/tier/role |
| POST `/auth/password` | Bearer、current_password、new_password | ok，撤销全部旧会话 |
| POST `/auth/logout` | Bearer token | ok，撤销全部旧会话 |

认证失败统一返回无效凭据，不区分用户名不存在与密码错误。注册重名返回 409，容量或限流返回 429；基础设施或安全配置不可用时拒绝服务，不降级为免密认证。

## 公网上线前

HTTPS 已由 Caddy 承担（`SITE_ADDRESS` 填域名即自动签发续期）。仍需数据库备份恢复、依赖/密钥运维以及容量测试。认证限流按 Caddy 覆盖写入的来源地址分桶；若在 Caddy 前面再挂一层代理（CDN / 云 LB），必须配 Caddy 全局 `trusted_proxies` 并把取值换成 `{client_ip}`，否则所有用户会塌进同一个桶——**不要改成在 Python 侧加环境变量来绕**。现有模型凭据在应用层按用户隔离，但用户级数据库权限进一步收紧属于 `PROD-CREDENTIALS.md` 后续方案；本次不声称能抵御已攻陷的内部服务或数据库管理员。
