# Pi 管理台实现计划

按现有持续执行授权，由本代理在当前会话实施，最后一次独立源码审查。设计见同日 pi-admin-integration-design.md；本计划不要求新增逐阶段确认。

1. 在干净管理员worktree快进main，合并Pi，解决3个浏览器脚本冲突，保留main业务更新。相关基线40项已通过，之后完整回归再决定合入main。
2. 在Pi分支实现 `ops/pi/admin_console.py` / `admin_publication.py`、原生socket宿主入口和systemd配置。接口：GET status、runs、events、daily、enhancements、operation；POST decision，闭合字段 request_id/actor_id/cycle_id/package_sha256/image_id/source_sha256/comparison_sha256/decision。原状态、费用、人工门禁和部署确认器不替换。先失败测试，再实现发布前准备、固定计划执行及元数据幂等；本阶段验证后合入管理员分支。
3. 管理员分支新增 `src/myink/pi_console.py` 固定本地客户端、`api/routes_admin_pi.py` 和配置。GET `/api/v1/admin/pi/{status,runs,events,daily,enhancements,operations/{id}}`，POST `/decisions`。require_admin与访问留痕在调用宿主前完成；输出限定、异常不可用、no-store。补身份/降权/不可用/副作用测试并导出OpenAPI。
4. 新增Vue `/admin/pi` 页面、类型化客户端和导航。状态/采样、日期/运行与事件详情、每日版本/变更/次日计划、候选确认/延后/操作进度；异步取消和权限变化清除旧数据。测试先覆盖数据语义与发布状态机；复用现有视觉系统。
5. 配置socket挂载的显式Compose覆盖文件与部署文档，完成真实本地Unix socket+API端到端、浏览器桌面/窄屏验证、完整回归及一次独立审查。审查作者修复后只做相关及必要完整检查，不重复审查。
6. 根据用户本轮授权将已验证的Pi和管理员集成合入main，提交推送，核对精确CI。保留原Pi未提交native fixture和main无关未跟踪文件；不擅自部署新的生产产品。

Review focus：过期候选或哈希漂移不得发布；认证/访问审计失败不得发命令；重复请求和宿主中断不得重放；损坏/不可用不能变成成功或空历史；数据/模型文本不进入HTML，服务凭据、会话、私有路径和SQL不进入面板。
