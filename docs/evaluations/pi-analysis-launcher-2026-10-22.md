# Pi 可信宿主分析入口（2026-10-22）

新增`ops.pi.analysis_launcher`把已有只读预检、持久30槽身份、原子费用预留与固定Linux Pi容器连接成一个宿主入口。实现提交`285e24b`；保留原Pi分支/worktree，不引入依赖、不合并main或部署。本轮只开发和合成验收，未请求真实provider、未读取或修改实际credentials/canonical账本，也未修改实际policy的`live_enabled=false`。

## 入口行为

`python -m ops.pi.analysis_launcher --config /absolute/private/manifest.json`默认只读。封闭清单固定scope/policy/input/evidence/code/runtime摘要、run_id、本轮cap、绝对deadline、原状态路径和本地Docker来源。正整数cap必须覆盖单次保守预留且不超过累计保守余额，deadline为未来600秒内、不得超过证据有效期；凭据0600、父目录0700、身份与固定deepseek-flash/官方Anthropic匹配。路径包括Docker CLI均采用绝对、非符号链接路径。

只有宿主显式`--execute`并满足live_ready，入口才在已经审批的原fee-only账本注册、绑定本轮预算。Ledger新增`existing=True`模式，使用`mode=rw`且在WAL配置前只读验证，避免缺失/空账本初始化。初次GREEN发现空文件会被journal_mode写入文件头，已由失败测试复现并修正；旧默认构造行为不变。

输入固定五组views/report，生成完整30槽；这个pilot只执行前两个槽，不自动重开或重试run_id。宿主只给worker当槽冻结slot/view/report、局部scope token和不超过45秒的绝对期限，不传上游key、原账本或私有路径。worker重建请求，仍无工具、同cwd、全新会话；宿主校验真实SDK请求、session、合同和单条已知结算，精确所属容器删除后才finish DONE并继续。unknown、请求漂移、超时、无效输出或清理失败均停止；历史未知完整预留不释放。完整30槽分母保留。

证据`pi-provider-evidence-v1`固定policy SHA、review_reference、valid_until及price/input_bound原始文件路径/字节SHA；清单再固定其canonical JSON SHA。这只是宿主审阅声明，验证文件完整性和有效期，不自动证明当前价格、在线密钥、usage语义或账单。本轮实际合成使用明确标注的合成证据和合成live=true策略，不能作为真实policy的校准或支出授权。现有严格usage解析未改，缺字段仍不补0。

## 验证

新增43项测试先RED后GREEN；审查后追加1项重复session回归，也已RED→GREEN。修复前定向231 passed；修复后完整Pi离线1991 passed、0 skipped、19项pi_lab/pi_live未选入（56.61秒），compileall及diff-check通过。覆盖只读check无副作用、清单/输入/来源/证据/权限/费用/期限拒绝、固定错误不输出私有路径，以及真实SQLite+loopback HTTP+本地stdio子进程的两槽、unknown、attach失败、超时、重复run与清理失败。未运行业务Python/Go/web或设施CI。

实际Linux验收使用固定Node24.22.0/Pi1.1.0和既有不可变Python镜像，复用runtime SHA`6e169d5462405f59c070365267eec24fddc005a3c141819ba7a1f548a592c528`，无依赖下载或升级。新源码闭包SHA`d7c120761c6b55802aee4fd3f04b2bd8c5e3fc1d01452f9ce96dc40ac59e7075`，worker SHA`0958bd4528d441c478b91699a3a03e7740b5fae02b5bc304237a21726dc2d87a`。

actual001因Docker CLI别名是符号链接在只读检查时拒绝，未创建容器、未请求provider；保留失败证据。actual002固定解析后的真实CLI路径，通过新launcher执行操作`d005d7ea-3ab4-4492-8e99-ef25fe83bf49`。两个新session分别为baseline/candidate，每槽HTTP`403/403/200/403`，合同/session有效、无工具、退出0；恰好两个MockTransport请求，已知结算。两个容器均exit0并删除，额外精确操作label的Docker ps为空，stderr为空。30槽为2 DONE/28 NOT_RUN，真实paid_requests=0。机器回执中的ledger/policy/余额均来自专用合成账本，不能解释为原canonical当前余额。

公开机器回执见同名JSON；原始帧和合成状态在本轮私有`.local/pi-analysis-launcher/actual-002`。独立审查发现1项Important：重复session在检查前已把第二槽写为DONE。已用真实SQLite/HTTP/子进程回归复现[DONE,DONE]，将唯一性检查移到第二槽finish前后GREEN为[DONE,UNCERTAIN]，完整1991项通过。无Critical/延期Minor；审查者43项通过，初次受沙箱阻挡的3项已在允许loopback的复跑中通过。`production_ready=false`、`automatic_execution=false`、`billing_verified=false`，45项语义质量仍unknown。

下一阶段是在明确本轮支出与期限的宿主清单下核对真实provider usage/计价维度，再评估有限真实只读分析对照。当前开发、只读预检和合成容器结果不授予付费启动，也不代表完整自主迭代闭环或生产验收。

修复后的最终actual003操作`a6c39e92-cb06-4be6-b8f6-5aaef9566b98`通过同一新入口两槽验收，两新session、每槽403/403/200/403、已知合成结算、退出0、两所属容器删除且精确label ps为空、stderr为空。新闭包SHA`7ac4909a3a90c10bc7e1e015e5daf62f38b26854d90f72848ba9bce81481ac01`，worker SHA`0958bd4528d441c478b91699a3a03e7740b5fae02b5bc304237a21726dc2d87a`；原actual002源码与证据保留，最终使用另建source-reviewed。当前最终实际回执为机器JSON的actual003_after_review，paid_requests仍0。

审查边界裁定：真实key/当前价格/usage/账单/质量不纳入本轮，代价是正式付费前仍需验收；实际Docker声明由实施方回执支持，若不符需重跑。信任宿主拥有的私有清单和快照，不宣称抵御任意特权宿主替换；若扩展威胁模型须增加不可变存储及宿主隔离。新增Ledger existing模式只用于本入口，旧调用保持原默认行为；缺失/空文件测试保护此边界。
