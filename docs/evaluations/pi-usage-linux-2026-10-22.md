# Pi usage 诊断 Linux 合成验收（2026-10-22）

当前源码 `bcb4bc65e1733ca8014cc3622a9d0512370941b1` 已刷新为独立 Linux 源码快照，在两个实际隔离容器中完成 Pi 1.1.0 / Node v24.22.0 合成验收。提供方强制替换为 httpx.MockTransport，使用新建的假凭据和合成账本；真实凭据、原累计账本均未读取或修改，0付费请求。公开机器回执见[同名 JSON](pi-usage-linux-2026-10-22.json)。

## 验收结果

- 重新复制既有固定 node/pi 运行时及当前生产 ops/pi 代码，不复制测试和缓存、不下载依赖或重建镜像。运行前后 `verify_source` 结果相同；runtime pin 沿用原值，code 指纹重新计算，具体摘要见机器回执。
- 默认 check 返回 checked，未创建结果目录；随后显式 execute 注册30槽，仅运行首对槽。结果为2 DONE、28 NOT_RUN，无恢复、重放或自动追加。
- 两槽各新建会话、合同有效，HTTP状态各为403/403/200/403，进程退出0；容器内为 aarch64、uid65534、网络禁止。两个容器均已删除，执行后按精确 operation 标签查询无残留。
- 0700结果目录中各有一个0600诊断文件，每个1468字节、恰好一条换行结束的 JSON，低于8192字节上限。schema、slot_index、独立 attempt_id 和合成账本逐项关联通过；公开 launcher receipt 不含原始计量或 attempt_id。
- 合成 message_start 的 input/output/cache_read/cache_creation 分别为17/0/0/0，各维度明确存在且为整数；message_delta 最终 output 为100。两笔终态均为 done、usage_known=true，按合成价格各计834微元、合计1668微元。这些数值只验证本地合成计量链。

私有入口为 `.local/pi-analysis-launcher/acceptance-usage-reviewed.py`，成功运行在 `actual-usage-002`，独立源码快照为 `source-usage-reviewed`。运行标识、摘要、日志和回执摘要见公开JSON；私有文件不入Git。

## 保留的失败与修正

首次 `actual-usage-001` 已完成两槽执行、结算及容器清理，但验收脚本把结算 evidence 与仅含费用/usage_known 的字典做完整相等比较，遗漏既有的空 `provider_request_id` 字段，因此验收断言失败。已只读核对实际账本，保留脚本、日志及首次回执；只修正验收断言，在全新目录完成第二次验收。没有修改产品代码。首次失败不记为验收通过；两次运行共4次合成 transport 请求，0真实请求。

## 边界与下一步

本轮只新增验收记录，未改生产代码，因此不重复上轮2017项离线回归，也未运行业务Python/Go/web或完整设施CI。实际 Linux 容器证据补足了[前次离线接线验收](pi-usage-launcher-2026-10-22.md)的运行边界，不证明真实 DeepSeek usage 语义、价格或账单。诊断仍为 best effort：验收脚本最多等3秒检查文件，产品入口未增加等待、重试或交付保证；本次恰好落盘不能证明未来都会落盘。

真实策略仍未启用，本轮不读取真实状态来重新声明其内容。原4.10元草稿仍不可执行，未自动改成真实配置。下一步应绑定真实五组输入、重新审阅当前价格/输入上界证据、明确预算与绝对期限并核对原累计账本，再安排有界真实响应和账单核对；缺计量维度仍保持unknown完整预留，不补零或自动重试。不合并main、不部署。

## 独立审查

只读审查结论为Critical0、Important0、Minor0；独立核对8项私有证据摘要、7项源码/运行时指纹、两份诊断、权限及两次合成账本结算，均与公开记录一致。审查未额外调用Docker；执行者提交前另行按两次精确operation标签查询无残留。真实provider/账单、原凭据/账本/策略及上轮2017项回归均未重验，保留为本次验收范围之外，不作通过声明。
