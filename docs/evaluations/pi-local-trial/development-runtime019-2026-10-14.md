# Pi真实开发019：候选已生成，冻结验收失败，未采纳（2026-10-14）

本轮安装的Pi完成6次真实HTTP200及6份完整usage，真实调用受控工具生成1个隔离候选补丁，并执行基线/候选检查。终态仍 **FAILED_OR_INCOMPLETE**：候选未通过冻结验收、未采纳、未发布。真实生成不等于验收通过；写作语义质量改善仍unknown，生产NOT_RUN。

## 真实补丁与失败原因

原基线保持 `dc6022b85b2556736ac3ac9d21e952105195025657a72d5f871405aca04dc597`。隔离候选为 `a130f2ad595f933175177fa5ee9e1071a4739884b51d4984100291c96dc142be`；唯一代码变化是 `_KEY_TOKEN` 后缀量词由 `{8,}` 改为 `+`，没有补齐字节前缀捕获机制。工具序列为 read_source → candidate_status → read_source → apply_patch → candidate_status → run_check；前5个结果非错误，run_check因检查失败被阻断。没有把失败候选当成后续基线，也没有将补丁写入公共产品源码。

| 冻结检查口径 | 基线 | 候选 |
| --- | --- | --- |
| 主表合成用例 | 52 | 52 |
| 字节保真失败 | 36 | 36 |
| 严重守卫项 | 16 | 16 |
| legacy安全用例失败 | 3/3 | 3/3 |
| 检查通过 | false | false |

16项严重记录分别为14项truncation_flag、1项credential_leak及1项aggregate legacy veto；legacy3例另列，不再加成独立主表case。失败计数delta为0，comparison objective_passed=false、severe_guard_veto=true、released=false。这些固定合成用例不是语义gold，不能推出写作质量提升或所有泄漏类型均已覆盖。检查回执的verified=true表示认证证据有效，检查结果本身仍failed。

适配器进程正常结束、session_valid=true、请求与工具均已settled；这不能覆盖blocked的run_check。停止阶段要求成功认证的patch和通过的最终候选检查，故ROOT reconciliation正确拒绝，controller rc1、整体监督verified=false；success/reconciliation文件没有生成。失败及候选均保留，未放宽parser、oracle或验收guard。三个所属树（Pi与双方checker）独立清理全部verified/tree_empty，准确keeper已停止，无固定测试UID残留。

## 预算、历史与关卡边界

当前累计 **83/100次尝试**：已知估算679900微元（0.679900元）加历史未知预留10065792微元（10.065792元），保守占用10745692微元（10.745692元），仍在20元累计上限内。本轮新增6次尝试、已知估算29867微元（0.029867元），未知增量0。**估算与预留不是供应商账单；83次是累计尝试口径，不能把所有历史记录称为已证实HTTP调用。** 没有每日重置、退款或未知费用重分类。

完整历史为246 operations/408 events；此前224行及370事件前缀不变，新增22 operations/38 events。阶段配额15/45/30/10保持：analysis聚合16＝继承4＋原始phase-admission12（其中blocked1），有效analysis transport15；develop30、experiment29、reserve8。pending model/admission均0，合法历史scope/fence pending保留。

本轮新gate1/gate2实际通过；gate2的3次模型传输是MOCK、0供应商HTTP，与之后6次真实付费调用分开。源码诊断55项、helper原39项及路径修复后56项通过均是离线范围，不代表完整业务服务或生产验收。prestart曾因冻结manifest的Windows分隔符在Linux被当成字面文件名而失败，修复和原失败已留存；它没有新增模型请求或改写H019冻结源码。实际018的OSError根因仍未确立，019诊断扩展不能反推旧失败已修复。

## 反馈判断接入与证据局限

[013反馈配对](feedback-runtime013-2026-10-14.md)已完成本机真实配对：30条冻结合成参考的分类一致数23→26，候选模型在其中10条unsafe_request参考上识别10/10，宿主对这10条拒绝10/10。**该10/10仅覆盖这10条参考，不是所有危险请求覆盖率。** 另20条non-unsafe参考含3条可疑安全指令，并非全是无风险反馈。标签是provisional而非语义gold；模型判断没有工具、预算、回复、resolve或删除权限。反馈实验、捕获保真检查与写作语义评价分别保留，不将分类一致性改写为写作改善。

| 保留证据 | SHA256 |
| --- | --- |
| 真实开发导出 | `35a083465b698298032b5cd9ff6e5827753c246d30ffe25fd172a80027ada252` |
| 冻结配对comparison | `f4041b754ec411964dd12ef6753bcc10faf2f71b30894b34645e5d20299f6cf5` |
| 完整JSON快照 | `b7ea258316f71aa0e00d98533eeb8f5f009fd24cad6644bd001d7035af081972` |
| 关闭后SQLite备份 | `2e74e24362d43f59433f5d882dab732858470ee2816879495ac38dd6d5b07c01` |
| 失败终态 | `df623a8af35cba01054848a259480838de55af506ec661641c48f24c0d14acdd` |
| 准确keeper停止 | `9a2bf8a79e91cf4a3adb57c85da861ad3f39a60f987f2eef4717dd628b8663a7` |

独立终态事实审查：`1a567de8f98415dddf977cbd6f8d009bbb18503ffd324585d109629b193c0c0c`；失败诊断：`12e38b4e44658afdfb4cab92da66c331ed05a2154d7ab14546aa5a872154227b`。审批仅覆盖保留事实，不批准候选采纳、生产或下一轮调用。公开稿仅包含聚合、工具名和哈希，不含用户正文、模型输出、完整账本、密钥、工具UUID或进程身份。聚合见[JSON](development-runtime019-2026-10-14.json)；前次gate2失败见[018](development-runtime018-2026-10-14.md)。
