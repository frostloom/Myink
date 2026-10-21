# Pi 原累计预算与本轮期限接入（2026-10-21）

范围：codex/pi-autonomy-design，起点9debd75。仅合成请求、临时SQLite、本地HTTP和模拟provider。没有外部模型、真实Pi进程、真实账本读取/写入、合并main或部署。

新增不可变本轮预算绑定与宿主槽位上下文，接入canonical reserve事务和现有网关。要求已有原20元fee-only累计scope，显式cap/deadline，重启不续期；同事务约束本轮与全局费用、防止同槽重复预留，未知本轮费用阻塞。HTTP接收、获取upstream、响应流和transport timeout受整轮期限限制。实现细节与宿主责任见[分析合同](../pi/analysis-and-scoring.md)。

验证记录：

- 初始新增32项RED均为缺失bind_budget失败，随后32项GREEN。
- 追加6项针对性验证：实际子进程预留后os._exit、历史退款不扩充本轮额度、绑定异常拒绝、替换账本拒绝、流超时迟到不退款、HTTP慢body到期。
- 首次相关回归257 passed/1 failed：已有slow_durable_reserve测试包装器不接受新增宿主keyword，按真实reserve签名增加透传kwargs；未改变其过期不发送的断言。
- 相关回归264 passed，0 skipped。
- 并发输入追加RED→GREEN：价格在锁等待期间恢复、max_tokens在锁等待期间恢复，以及预留后宿主修改原body；快照贯穿计价、校验和实际转发。新增测试最终41 passed，0 skipped。
- 扩展测试时误替换旧锁等待测试的body变量，复跑复现NameError，已恢复该局部引用并重新验证；失败结果不计为通过。
- 独立只读审查及快照窄复核无剩余Critical/Important/Minor；审查者最终38 passed、3项HTTP因其沙箱权限未运行。主执行者已真实运行全部41项（含3项loopback HTTP），未跳过。
- 完整offline ops：`1809 passed, 19 deselected in 44.63s`，JUnit确认failures=0/errors=0/skipped=0；19项为pi_lab/pi_live未选入。`python -m compileall -q ops/pi`和`git diff --check`通过。原始日志与JUnit保留在忽略的`.local/pi-run-budget/`。

限制：本轮没有新增实际费用/期限授权，没有发付费请求；不是生产自治。历史未知预留保持保守计费。自定义transport阻塞线程不能在Python中强杀，真正运行时隔离与进程清理是下一目标。现有45项语义指标保持unknown；业务服务完整CI未运行。

期限证据边界：在期限前获得完整EOF/usage后，SQLite提交等待跨期限不属于迟到模型响应，不因此改写原结算语义。真正期限后才到达的响应流拒绝并保留unknown。
