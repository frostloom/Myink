# Pi 有界真实诊断（2026-10-22）

本轮按用户开始有界真实诊断的授权，使用deepseek-flash和原累计20元账本实际发起1次模型HTTP请求，上游返回200及text/event-stream；随后宿主入口因UnicodeDecodeError停止。没有执行第二槽，也没有重试。完整用量、合同和账单均未验证。公开机器回执见[同名JSON](pi-live-diagnostic-2026-10-22.json)。

## 放行与实际结果

在提交23012fa的已验收代码上重新核对完整025输入、当前Linux闭包、固定daemon/image以及原scope/policy/账本身份；三份当次官方来源字节与此前审阅版本一致。使用原CC-Switch导入凭据，通过生产`_provider`发送，未使用MockTransport代替真实调用、未增加重试或跳转。只读余额查询不属于模型调用。

独立冻结本轮run-policy，仅将live_enabled由false改为true，其余字段与原策略逐项相等；原全局策略继续live=false，原凭据、原025输入/报告字节未改。新清单冻结4.10元费用上限和240秒绝对期限，check返回launch_ready=true后仅调用一次execute。已过期清单不得重放，本轮run不能恢复或补跑。

实际仅首槽创建1笔model-attempt并发起1次上游HTTP，返回200后宿主在解码转发正文时失败。usage诊断文件为0700结果根内的0600文件，270字节、单条完整JSON，stream_started/stream_stopped/final_output_usage均false，raw_usage为空、parser_reason=missing_start。parser_valid=true只表示尚未捕获事件触发解析错误，不能当成用量有效或完整EOF证明。没有获得真实四维usage形状，也不能判断是哪一个缓存维度缺失。

30槽为0DONE、1UNCERTAIN、29NOT_RUN。容器被强制停止，退出137后删除；这是清理成功，不能记为Pi进程成功退出或合同通过。按精确operation标签再次查询无残留。失败类型、attach及usage诊断和未知记录已保留；完整异常消息/traceback和可验证会话结果未取得。

## 金额与原账本

首槽按现有规则保留2.016384元完整预留，终态uncertain、usage_known=false；这是保守占用，不是已核定实际消费。原账本由208次/202已知/6未知变为209次/202已知/7未知，无pending；已知估算费用仍1.791431元，未知预留14.098560元，累计20元内保守剩余4.110009元。没有释放旧未知或本次预留，没有另建金额池。

执行前使用SQLite一致性备份保存在私有目录；只读比对确认执行前642条operations逐条不变，1085条原events为当前事件序列的相同前缀。仅追加本轮36条操作、39条事件。

只读账户余额端点在调用前后均返回成功，本次可见CNY余额差为0.00。该接口观测精度、记账延迟和同账户CC-Switch并发使用均未排除；零变化既不证明此次免费，也不是逐请求账单证据，不能据此释放预留或声称billing_verified。

## 解码调查及下一步

代码中的DeadlineUpstream对尚未消费的流使用iter_raw，HTTPX默认可能协商压缩。已用完全本地MockTransport构造gzip SSE，确认原始压缩字节会直接到达relay的UTF-8解码，并复现同类UnicodeDecodeError；该复现没有额外真实请求。真实本次transport记录只有content-type/状态/request-id，没有保留Content-Encoding或正文原始字节，因此不能据此断言实际根因就是gzip，仍需离线修复和验证编码边界并补足安全的编码元数据。

下一步应先离线验证真实transport的编码协商/拒绝或有界解压方案及安全响应元数据，在已知编码的MockTransport和实际容器中验证；不要以重发旧槽来诊断。任何后续真实试验都需要新的运行身份、当前余额/证据与有效期限，并继续保留本次unknown和累计预算。真正的usage语义、提供方逐请求账单和业务质量仍待验证。

本轮未改生产代码，没有重复上轮2024项完整离线测试；新增验证为本地编码故障复现、原账本保留和精确容器清理检查。未运行业务CI、合入main或部署。私有原始证据在忽略目录`.local/pi-live-diagnostic-20261022/`，公开只保存无正文摘要；不含密钥或其摘要。

## 独立证据审查

只读审查Critical0、Important0、Minor1：建议精确限定异常留存，已将“完整保留失败”改为“保留失败类型，未取得完整异常消息/traceback”。16项证据摘要以及公开金额、来源、清理、诊断权限/大小和余额差均与私有回执相符。审查没有新提供方或Docker调用，也未读取原凭据/原输入正文；原状态字节保留依据执行者内存比较及回执，当前容器状态依据执行者最后精确标签查询。真实编码根因、实际费用/usage语义/质量及上轮2024测试未重新验收。编码假设需后续验证，未知费用继续占用；本次审查不构成再次付费、合入main或部署授权。
