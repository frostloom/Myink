# Pi 可信宿主分析入口

继续用户已授权的Pi开发、提交推送与myink记忆；不再询问。原worktree和codex/pi-autonomy-design，Python3.12，无新依赖。此轮实现与合成验收，不开启实际私有policy.live_enabled，不发送真实付费请求，不合并main/部署。

新增analysis_launcher：可信宿主选择封闭JSON清单，固定原ledger/policy/credential/input/evidence/source路径，run_id、cap_microyuan、绝对deadline及scope/policy/input/evidence/code/runtime SHA，Docker可执行路径/本地daemon/不可变image。只接收DeepSeek官方Anthropic端点和deepseek-flash。输入为完整五组views和report，生成既有30槽；本入口仅执行前2槽，新会话、无工具、同/work/candidate。复用原AnalysisRun及预算预留，不建新scope、钱账或重启重发。

默认check只读，不构造Ledger、不创建目录、不联系daemon/provider。核对policy/schema2 fee-only累计20元、credentials四字段与0600/0700、完整source闭包和输入身份、只读账本及原scope审批链。cap必须为正整数且可负担单次保守预留、不得超过累计保守余额；期限必须为未来600秒内，且不超过证据有效期。显式execute且live_ready才可创建run并绑定预算、启动容器。既有私有策略保持live=false。重复run_id不重开、不恢复、不自动重试。

证据是宿主独立审阅记录，固定policy SHA、review_reference、有效期、价格及输入上界的原始文件路径和SHA；验证文件及有效期并冻结记录SHA。它表示宿主审阅声明，不自动证明当前价格、key在线有效、usage语义或账单；缺字段不补0。发送前在既有原子预留中再次检查原scope、同policy/slot、本轮和累计预算、deadline；实际余下时间限制attach、loopback与provider。历史unknown仍全额计入，新的unknown阻止下一槽。

容器只挂固定只读worker与封闭source，保持network none/non-root/只读/资源边界。初始stdio帧传当槽slot/view/report、局部scope token和不超过45秒的绝对期限，不传provider密钥/ledger/私有路径。worker重建并校验slot，宿主继续校验真实SDK请求、session及合同。原固定合成probe入口保留，不能变成真实provider开关。实际首次仅合成provider验收此新路径。

每槽HTTP负控/实际请求/重放应为403/403/200/403，恰好一条该run/slot的已知结算。只有宿主合同验证、计费已知及所属容器清理全成功后才finish done并前进。失败保留已有claim/完整预留，结果blocked；绝不把NOT_RUN写成完成。所有finally分支协调pending create并只清理精确所属容器，未解决对象公开无正文身份用于恢复。根目录必须新建0700，私有原始帧/结果仅在其中；公开回执不含正文、key/其hash、scope token或私有路径，异常只给固定错误/类型。30槽保留分母2 DONE/28 NOT_RUN，production_ready/automatic_execution/billing_verified保持false。

验证：先RED后GREEN覆盖清单/证据/凭据/输入/来源漂移、费用/期限、check零副作用、live关闭拒绝执行；真实SQLite+HTTP+本地子进程模拟容器边界验证完整两槽/unknown/重放/清理失败/崩溃/过期。更新固定worker的通用初始帧并保留legacy probe。定向与完整Pi离线回归，条件允许用固定Linux Pi和MockTransport运行新入口实际两槽；独立审查后提交推送/更新myink。
