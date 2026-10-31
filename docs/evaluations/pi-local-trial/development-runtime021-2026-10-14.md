# 本机 Pi 真实开发 021：机械局部改善，验收仍失败（2026-10-14）

ROOT已核对物理导出，独立终态事实与诊断审查已冻结。事实审查只认可已记录的失败、机械结果和预算状态，不授权采用候选或再开运行。

021 运行安装版 Pi 和真实模型，完成7次 HTTP200及7条完整 usage。Pi 自己生成两处隔离补丁，完成最终 candidate_status 和一次真实 unit 配对检查，共8次工具调用。adapter 为 done、session_valid=true、settled=true，所属三个进程树清空；控制器 rc1，非超时失败。正常结束模型会话不等于通过开发验收。

两侧 checker 回执均 verified=true，但 result=failed、status=blocked。核心 verify_stopped_phase 要求成功的 run_check，因此整体 root reconciliation 未通过；final status 的真实回执与工具记录可对齐，不能据此称 root gate 成功。实际导出没有 reconciliation.json 或 success.json，私人最终状态守卫在写文件前拒绝。候选未采用、未发布。

| 冻结机械量表 | baseline | candidate |
| --- | ---: | ---: |
| 52条主案例 fidelity通过 | 16 | 22 |
| 52条主案例 fidelity失败 | 36 | 30 |
| redaction / encoded_caps / input_immutability | 均为1 | 均为1 |
| 另3条legacy安全案例 fidelity | 均false | 均false |

原 basic 与 maxtext 两族共12条改善，redaction-12族新增6条失败，净增6条 fidelity通过。宏选择的6个组各取一个案例，聚合 delta=1、status=improved；这只是选中子集，不能写成全部52条通过，更不是独立语义gold。候选 legacy 的 severe 列表为空，但三条 fidelity仍失败，聚合 legacy absolute veto=1；objective_passed=false、severe_guard_veto=true仍阻止采用。

静态定位显示 capture 以字符长度触发裁剪，忽略实际转义后的编码字节；逐字符 JSON 编码额外计入引号，造成前缀保留不准。另一处正则把8字符的安全字段标记 api_key= 吞作敏感值，导致新增 fidelity失败；不能把这次失败归因为三条 legacy 的凭据泄漏。本说明不包含原始模型会话、用户正文或 token。

候选单文件 SHA 为 `6fe3b4367326a349078c94c6b8cf6f0084fa936a2b683b5aa6e2940744056686`（8369字节），工具使用的候选聚合 SHA 为 `6d606e9281a121a05012a4f8f25b27622f2b89e4dd594c17f01b508c7031a06a`，两者不能混用。原 DC baseline与隔离工作区既有18项改动保持，不把隔离候选覆盖到 main。

终态累计94/100次尝试：已知估算0.743202元、未知预留12.082176元、保守占用12.825378元，不是供应商账单。本轮新增已知估算0.044910元、未知0；旧未知占用未退款或重分类。完整快照288 operations / 481 events，原262 / 436完整保留，新增26 / 45包含一次批准操作及两个批准事件。pending model-attempt与phase-admission均为0，合法scope/fence pending仍保留；keeper已精确停止。

原100次 / 20元与阶段15 / 45 / 30 / 10不变。analysis聚合16为继承4加raw12（含旧blocked1），有效transport15；develop41、experiment29、reserve8。全局余6次、develop余4次，不能把当前8-call Plan当作已授权完整新轮，不自动重试或改配额。

配对 checker实际运行，候选产品pytest、完整服务、生产接入和main采用均NOT_RUN/false。新gate2验证真实Pi工具协议，模型响应SIMULATED，不是这7次付费请求或业务成功。[013反馈对照](feedback-runtime013-2026-10-14.md)仅覆盖30条合成参考：分类23→26，host危险参考拒绝10/10，不代表全危险覆盖；生产反馈数据库NOT_RUN。见[反馈维护说明](../../pi/feedback-triage.md)。写作11域45项指标语义仍unknown，不从这次机械量表推导召回、抽取或性能改善。

[聚合JSON](development-runtime021-2026-10-14.json)记录物理证据哈希与上述口径。终态事实审查 SHA256 为 `b482d3998f6bef5befa63a9dd97606ba7aa44acd165c5b65e3e9232a8a1df7a2`；诊断 revision002 为 `46d29ed9f7cc319857162a08f9e27c27aefc70b0d92ca993467dc3d78d5c90a2`，原诊断版本保留。旧020失败与unknown历史原样保留。
