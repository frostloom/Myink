# 面试准备 P0 验收记录

日期：2026-10-08。基线提交 `326c4b366cdae38c374d253b12340c63615133c1`。本轮修改尚未提交、推送或部署；没有付费模型调用，没有读取或写入开发/生产作品库。

## 交付

- P0-01：README 更新为已部署的小范围 MVP，补面试入口；旧 BACKLOG 标注历史；INTERVIEW-ROADMAP 覆盖 P0/P1/P2、条件性探索与验收依赖。DEMO 区分历史 smoke 和新验证。
- P0-02：`scripts/render-interview-demo.py` 从原始 `workflow-recovery.json` 生成独立 HTML，18 个已留存节点可筛选、展开；原始数据的 SHA-256 随产物显示。明确没有完整正文/diff/模型配置，不能冒充当前版本质量评测。
- P0-03：工具逐项执行预算；超预算调用不执行，但给每个 tool_call 回结果并记录 skipped；零预算直接最终输出。人物/事实工具缺省章号取任务章号，显式历史参数保持，原模型参数不被原地修改。更新一项既有集成测试，轨迹应记录绑定后的实际参数。
- P0-04：用户级 Archify 安装完成。项目总流转图、语义 JSON、产物验证和浏览器/截图回执位于 `docs/diagrams/2026-10-08-runtime-flow/`。以通过的总图交付，单章完整细节在图目录 README 的路径表中。

## 测试先行与实际结果

修复前新测试：**6 failed / 4 passed**。失败分别覆盖零/一/三次预算下同轮五次调用、多轮累计超预算、人物和事实缺省章号缺失。修正了测试辅助函数的参数命名冲突后，才以这些业务失败作为复现证据。

第一组纯聚焦回归：**37 passed / 1 deselected**，排除的一项依赖活库，未当作通过。

随后启动专用 Compose 项目 `myink-interview-p0`，使用临时 PG tmpfs、Redis、RabbitMQ（15432 / 16380 / 15673），不运行真实 worker。初始化命令 `python -m myink.cli init --seed` 完成退出 0。

最终集成命令：

```text
python -m pytest tests/test_tool_boundaries.py tests/test_context_budget.py tests/test_admin_observability.py tests/test_flow.py tests/test_review_routing.py tests/test_manual_plan.py -q --tb=short
```

结果：**97 passed，28.26 秒，无 SKIP/xfail**。覆盖完整章节/批次图、工具循环、预算、快照、审核路由和人工计划。模型/embedding 使用替身。第一次集成运行 96 passed / 1 failed：旧轨迹断言未包含新绑定的章号；按行为更新预期后运行同一组通过。

环境处理：本机 Python 未安装 pyotp，下载到临时目录，不改全局环境或依赖清单；测试使用本机已有其他依赖，不声称与生产锁定环境完全一致。Windows 初始化脚本 CRLF 导致测试容器退出，使用临时 LF 副本与 override；控制台 GBK 无法输出勾号时改 UTF-8 后幂等重跑。未修改部署文件。

## 产物与浏览器

- 离线案例：Chrome / CDP 在 **1440px 和 390px** 检查 18 个节点、3 个审核、1 个人工修订、2 个保存节点的筛选、展开/收起和横向溢出，均通过。回执：`interview-demo-browser.json`。
- 案例重建：确认重建前后源字节不变、输出相同；源哈希和 18 个节点与记录一致。
- Archify：showcase validate / deliver / strict check / browser-check 均 pass，零诊断；独立 visual-check pass，四张亮暗主题截图。实际查看 1440×900 的亮暗两张；自动门禁和实际视觉检查分别记录。
- `git diff --check` 通过。本轮没有改变 API 契约或 web 源码，未跑前端三项或导出契约。

## 验收边界

未运行全量 Python 测试、镜像构建、生产容量测试或新的真实模型效果实验。历史真实模型记录不是本轮生成，也不能证明混合召回或 Reflexion 的改善幅度。后续按路线图进行 P1 对照与失败分析。

验证结束后清理本轮专用容器/网络，将本轮临时依赖和辅助文件移入被忽略的 `.local/interview-p0-work/`，保留原有未跟踪文件与其他服务。实际状态检查见本轮交付时的 Git 状态；不把无关文件纳入提交。
