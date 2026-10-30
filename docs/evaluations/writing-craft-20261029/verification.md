# 本地验证记录

2026-10-29，使用 worktree `src` 的 PYTHONPATH；禁用dotenv，所有PG/Redis/RabbitMQ检查只连接专用 `myink-test` 实例15432/16380/15673，不启动真实worker，不调用模型。

- 较早针对性资源/文风/建书/衔接回归：205 passed；最终缩小方案针对性135 passed。
- 新兼容修复与发布保护纯测试：23 passed；独立审查复跑两份新增测试7 passed。
- 最终全量Python：**2233 passed、1 skipped、5 xfailed、2 subtests passed**，267.18秒。
- 跳过和既有预期失败未算通过。两条warnings为既有Starlette弃用和HS512测试密钥长度提示。
- `compileall`成功，`git diff --check`无输出。
- 首轮全量有3失败：一处API说明契约未重导出、两处仍断言旧万能开头/章末禁令的测试。更新了预期行为断言，重导出后仅style-library说明文字变化，最终全量通过。
- 沙箱内直接运行需要PG的测试曾被本地TCP权限阻止，未算通过；最终全量在允许本地网络的隔离环境重新执行。

没有修改前端或Go代码；没有声称前端/Go此次重新测试通过。此次尚未构建发布镜像，也未提交、推送或部署。

文学效果实验和工程回归是两个验收维度，工程绿灯不抵消候选写作效果未通过。

最终源代码方案经独立真实镜像效果验收仅1/6通过，未达到发布条件。工程通过与文学验收失败分别保留，不提交或发布。

## Latest output-integrity regression

Full Python run after the length guard and first2regression tests:2264passed,1skipped,5xfailed,2subtests,2existingwarnings in314.26s. Raw log:regression-20261029.log. After collection,2more artifact/bounded-exhaustion tests were added; all4truncation tests passed, then complete retry/provider-finish/streaming/budget-provider files45passed in3.56s. No additional production changes after these checks. Temporary myink-test containers/volumes cleaned up after tests. Independent scoped review found no concrete guard regression; supplementary tests cover recommended stream/retry gaps. This does not establish prose stability. No frontend/Go change or fresh test claim.

## Latest complete run after corrective-turn fix

Full current Python2272passed/1skipped/5xfailed/2subtests/2existingwarnings in251.93s. Covers JSONnewuserturn, lengthrejection, streamrecovery, helperbinding and all budgetprovider tests. Rawlog regression-retry-turn-20261029.log. Temporaryteststack subsequentlyremoved. Earlier accidental scoped invocation after infra removal produced18DBsetup errors and1sandboxlocalhostbindfailure; not counted as verification, resolved by this fresh isolated full run. No product-code change after this run. Subsequent experimental runner only changes source-id encoding and <=8-cell batches, checked with exactcoverage/provenance localassertions. No frontend/Go fresh claims, deployment still pending qualitygate.

2026-10-30 patch output-integrity follow-up: full Python2275passed/1skipped/5xfailed/2subtests/2existingwarnings,274.98s; new node_patch length guard RED→GREEN, provider-error priority and normal stop controls included. See regression-patch-truncation-20261030.log. Effect gate remains failed/uncertain; no release.
