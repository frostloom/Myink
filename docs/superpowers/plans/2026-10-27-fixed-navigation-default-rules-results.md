# 第三轮端测修复记录

## 已实施

- 用户与管理导航使用统一固定视口尺寸；桌面左/上 12px，高度为视口减 24px，正文共享占位；手机使用固定 60px 导航条。
- 完整题材按信息区块分栏；名称/故事钩子合成短行，保留全部内容与开书准备折叠详情。
- 创作规则、表达规则在作品快照首次初始化时自动选用，优先个人版本；旧作品补齐缺失种类，保留既有规则和个人覆盖。
- 初始化通过项目锁序列化并持久标记，重复读取不追随平台更新；已入队任务仍使用原快照。界面自动规则不可取消，但允许编辑，文风可选。

## 验证结果

- 前端完整测试：共享 202 + Vue 698 = 900 passed。
- lint：0 errors，9 条已有警告。
- 默认规则 SQLite 139 passed；隔离 PostgreSQL 目标 153 passed，另两条旧入队契约更新后重跑 2 passed。
- 完整后端：2039 passed、1 skipped、5 xfailed、2 subtests passed。跳过项需要明确批准的 localhost:15432 评估数据库，未绕过隔离边界；5 项为既有预期失败。
- 生产构建与类型检查通过；保留已有大包警告。
- Chromium / Firefox / WebKit：18 组、306 项检查全部通过。使用隔离模拟 API 与真实浏览器，不代表真实模型调用端测。
- 完整修仙题材字段逐项存在，桌面/手机高度与横向溢出检查通过；固定导航尺寸、滚动锚定、正文占位通过。
- 专用 PostgreSQL / Redis / RabbitMQ 测试栈已清理。

## 本地更新

已备份数据库，使用专用迁移服务完成新增标记列，再切换 API、worker、Caddy。
本地镜像为 `feedback-round3-20261027`；release `vue-00777bbf22aacb2ee5b126bedbf849fc8b406505d20c35962eb8b096833c973a`。
线上本机 HTML 摘要、release 与测试产物一致；137 个已安装 Python 源文件摘要匹配；readyz 的 DB/Redis/worker 均正常。旧镜像、回退脚本和数据库备份保留于 Git 忽略的 `.local/feedback-round3-20261027/`。

回归证据：`/tmp/myink-round3-frontend-full.log`、`/tmp/myink-round3-python-full.log`、`/tmp/myink-round3-lint-final.log`、`/tmp/myink-round3-build-final.log`、`/tmp/myink-round3-verified-matrix/receipt.json`。

本轮不提交、不推送、不更新远程。不含 Pi 变更。保护已有未提交修改。
