# Pi 修复后真实诊断（2026-10-22）

用户在明确说明“将本次私有写作输入和报告发送DeepSeek、最多两次请求、上限4.032768元”后回复“允许”。此前审批拦截仅是历史状态，本次以该明确授权执行。使用新run_id、固定修复078060c后的源码、原累计20元canonical账本和新生成的240秒期限；全局策略仍live=false，本轮独立策略仅切live=true。三份官方资料在线刷新后SHA与既有审阅一致，输入、源码闭包、运行时/daemon/image和账本身份均核对通过。未改全局策略、凭据、原始写作输入或CC-Switch。

## 实际结果

实际发起1次production deepseek-flash模型HTTP请求，无MockTransport、自动重试、重定向或fallback。上游200 SSE，诊断content_encoding=absent；message_start已被读取解析，没有再次出现UnicodeDecodeError。该有限观察不能倒推上次真实失败必由gzip造成，也不代表整个provider链路验收通过。

入口最终blocked，failure_class=ValueError；首槽UNCERTAIN、第二槽未启动，30槽仍0 DONE/1 UNCERTAIN/29 NOT_RUN。attach保留119155字节、三条请求帧（错误token、请求漂移、实际请求），未取得结果帧或可验证session/合同。容器强制停止exit137并删除，按本operation精确label的Docker查询为空；这证明清理成功，不能写为业务进程成功退出。

私有usage诊断958字节，0700父目录/0600文件，单条完整JSON；stream_started=true、stream_stopped=false、final_output_usage=false、parser_valid=false、parser_reason=invalid_start_usage。message_start四个数值字段均存在：input137、output0、cache_read6400、cache_creation0；另有service_tier，没有未识别的额外key。诊断不保留service_tier的原字符串值。当前严格_usage_updates拒绝service_tier，离线用同数值和合成metadata复现：含service_tier时拒绝、移除后start可解析。只说明用量起始解析机制，不证明完整用量、cache语义或账单。

不能把该用量拒绝直接认定为宿主ValueError的根因：collector失败仍会转发正文；宿主保存结果帧之前已抛ValueError，但完整异常消息/traceback、原上游响应和字节计数没有保存，具体触发点未知。下一步须先离线定位宿主relay/协议/大小等拒绝分支并增加有限原因码，同时独立评估service_tier兼容规则；不得仅放宽用量校验后再次付费碰运气。

## 账本与费用

单次2016384 microyuan完整预留保持unknown，不释放、不重发。累计210 attempts：202 known、8 unknown、0 pending；known估算1791431、unknown预留16114944、保守已用17906375，余额2093625 microyuan（2.093625元）。预留不是核定消费。

写入前一致SQLite备份与写入后只读比对：原678 operations逐字段/值不变，原1124 events为完整相同前缀；只追加36 operations/39 events，历史unknown未改写。全局live=false，原凭据及输入字节未变。

调用前后只读账户余额GET均成功，可见CNY总余额减少0.25元。这只是账户级观察，未排除精度、入账延迟或并行CC-Switch用量，不能归因成本次请求账单或用于释放预留。actual_spent_microyuan=null、billing_verified=false、provider_usage_semantics_verified=false、contract_verified=false，45项语义质量仍unknown。

## 校验与后续

本轮没有生产代码改动；此前2042项离线回归未重跑。私有verify-result核对请求/attempt/冻结槽身份、单次请求、诊断、金额、原账本及事件前缀、当前精确label清理与global live=false，并离线复现用量start拒绝，额外provider请求0。公开机器记录只含数值、有限类别、来源与证据摘要，不含凭据、正文、原header或私有request/attempt身份。

本次有限诊断已结束，第二槽未运行，不继续付费、不恢复本run、不释放历史unknown、不合并main或部署。后续离线定位和验证完成后，任何新的真实运行仍须重新形成费用/期限清单；本次授权不是无限次启动授权。

独立只读审查已完成：无Critical/Minor，发现并修正2项Important（旧JSON把历史check账务与执行后混在同对象；旧Markdown误把usage拒绝并列写作停止原因）。当前无未解决发现。审查者独立核对6份允许证据SHA、源码提交/provenance、槽数/usage和账务算式一致；完整24份SHA采用实施方public verifier已通过记录，原678 operations及1124 events保全采用三份一致私有证据，未独立重做SQLite逐字段比较或Docker查询。未读取凭据、写作正文或原attach，未发新请求。
