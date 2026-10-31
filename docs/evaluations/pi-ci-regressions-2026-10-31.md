# Pi CI 故障定位与回归

[原浏览器失败](https://github.com/frostloom/Myink/actions/runs/41176921031)为 WebKit readiness：最终零页面异常断言收到章节 GET 的 access-control 错误。该请求为同源合成 fixture；错误栈位于已有异常处理的正文加载函数，发生在包含硬刷新/跳页的用例中。本轮让硬导航前等待有限 API 响应体结束，持续 SSE 不参与等待，不过滤错误或放宽断言。三引擎各31项检查通过，各完成9次导航前请求等待，page_errors/unknown_routes均空。间歇性故障仍需远程 Linux WebKit 回归确认。

[后续 Python 失败](https://github.com/frostloom/Myink/actions/runs/41179523238)为真实 PostgreSQL 维护 CAS：PostgreSQL JSON 时间会删除微秒尾零，原代码生成的完整六位小数与读回值字符串不同。固定时间参数100000/123450微秒稳定复现2失败；0及123456通过。现按PG格式生成期限，保留完整行CAS、再次读回确认和未知失败保持关闭。隔离PG17432的5项维护/CAS用例及18项发布回归共23通过。

当前成品 Pi 管理台也已用 Chromium/Firefox/WebKit 各12项检查复验，构建index SHA与main产物 `3fcdda72ae5455deb2ac0defc0de4a759e8e47774f3ced9592c009b9b9d85629` 一致。浏览器清理和回执脚本8项通过。首次本地完整矩阵误用了worktree残留旧构建，已停止，该轮失败不计为当前源码验收；原始日志保留。

由于公开日志/工件下载要求身份，临时CI任务仅用自身actions:read读取指定历史回执/日志并输出截断、转义摘要；现已删除，workflow逐字恢复main原四项门禁。永久保留有长度限制且转义的失败注解，未来能定位具体浏览器/阶段。没有增加重试、跳过或continue-on-error。

[机器回执](pi-ci-regressions-2026-10-31.json)保存本地验收；最终远程CI仍需读取实际结果。生产未改、未产生模型调用或账本变更。原先准备的334bd305桥接runtime尚未包含本次期限修复，实际安装前必须从最终修复提交重新构建并记录pin；不能把旧归档当最终桥接发布产物。
