# Pi 网关计费前校验验收（2026-10-20）

## 本次交付

在 `codex/pi-autonomy-design` 分支给实际 HTTP 网关加入可信宿主 `request_guard`。经过认证和严格 JSON 解码后，只在宿主明确返回 True 时进入原预算预留与模型转发流程。服务入口 `serve_gateway` 同样传递此函数。

冻结输入有漂移、未被宿主允许、函数异常或非布尔 True 返回值时，返回403，不进入模型转发和预算预留；错误详情不公开。此接口默认未配置，保持原调用兼容。

## 验证证据

- TDD RED：新增15项测试先全部失败，原因为接口不支持 `request_guard`；exit1，2.53秒。
- GREEN：相同15项全部通过；exit0，10.37秒。
- 相关回归：171 passed，0 skipped，exit0，38.31秒。

回归命令（仓库根目录）：

```text
python -m pytest ops/pi/tests/test_gateway_admission.py ops/pi/tests/test_model_gateway.py ops/pi/tests/test_pi_gateway.py ops/pi/tests/test_controlled_integration.py ops/pi/tests/test_tool_proof.py ops/pi/tests/test_analysis_execution.py ops/pi/tests/test_analysis_contract_probe.py ops/pi/tests/test_budget.py -q --tb=short
```

新增测试经真实 loopback HTTP 服务调用已有网关，使用隔离 SQLite 账本与 mock provider。冻结请求测试直接使用 `verify_contract_request`，覆盖两条 messages 路由，检查先校验后预留；拒绝后累计尝试与费用均为0，允许后按原 usage 结算为1次、54 microyuan（纯测试数值）。另覆盖认证/重复JSON字段先于校验、错误宿主配置启动拒绝及服务入口传递。

本机 JUnit 证据：`E:\github项目\Myink\.local\pi-admission-20261020\regression.xml`，含测试结果、不含真实用户正文或密钥，不是已上传 GitHub 的文件。

## 尚未完成

此接口不提供持久化槽位游标、并发防重放或整轮授权。宿主仍需将当前槽位的校验与消费做成原子持久化操作，绑定整轮次数/费用/期限，再完成当前源码版本的严格进程隔离和清理验收，才能开始30槽真实模型对照。

本轮外部模型请求0；未改写原累计20元账本、未释放旧未知预留、未合并main、未部署。没有运行全项目业务CI，也没有运行新的真实Pi进程/外部模型质量对照；171项是上述定向回归，不能替代这些验收。
