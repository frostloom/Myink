# Pi 真实输入绑定与初始帧修复（2026-10-22）

已把025的完整五组真实视图和原报告、当前代码/固定Linux运行时、原累计账本身份及当次官方价格/容量证据绑定成完整私有清单，默认入口返回`checked`。策略仍`live=false`、`launch_ready=false`，没有调用execute、没有注册新真实槽位、没有付费请求。公开机器回执见[同名JSON](pi-real-input-binding-2026-10-22.json)。

## 阻塞与最小修复

初次实际准备被`analysis_launcher._prepare`的初始帧校验阻止：完整原报告按传输编码约299625字节，首对完整初始帧354924/355054字节，超过共用的196608上限。实际模型请求仅33225/33352字节，在既有65536限制以内。没有裁剪报告、视图或来源，也没有改提示词与合同来通过检查。

新增`INITIAL_FRAME_LIMIT=524288`，只用于可信宿主发给worker的第一条完整冻结输入，包含结尾换行；launcher预检、stdio首写、worker首读及解码后校验共同使用。后续relay/reply/result继续196608、HTTP正文65536、总输出1048576字节；费用、期限、无工具和网络隔离限制保持不变。七项合成回归中三项先RED，覆盖完整大报告、冻结请求一致性、实际stdio含Unicode/换行的精确边界、超长/漂移拒绝及运行relay限额。首轮修改漏改worker的旧常量引用，9项出现NameError；已修正并保留日志，相关93项通过（5.22秒）。

## 完整真实配置

原025清单身份`646270e7ea7b58d76950050934f78afe5f4ee0a7fb87e322298e63b04bc5beb7`及原报告文件SHA`0a58a5e69680379c93edfeec6bfe4bd629db32724811648efc67debf91ed65f6`重新核对一致。五组分别取清单中对应的完整view，逐组input_sha核对通过；冻结清单未重用旧grant，模型固定deepseek-flash和共同cwd，30槽请求已重算。真实inputs私有文件496153字节，未使用合成资料替代；45项语义质量仍unknown。

本次重新获取三份官方公开资料，来源字节摘要见JSON；价格与输入容量证据只作为宿主审阅声明，缓存语义和真实账单仍未验证，未增加缺维度补零。输入容量1M为官方上下文的保守上界，不是tokenizer实测校准；cache_write使用全价输入保守上界。

原账本只读复核仍208次、202已知/6未知/0pending，已知1.791431元、未知完整预留12.082176元，保守余额6.126393元。两槽上限4.10元、240秒，每次最坏预留2.016384元；两次4.032768元，小于本轮cap及原余额。首槽unknown、合同无效或清理失败即停止，无自动补跑或重试。准备前后原输入/报告、DB/WAL、policy与credential字节相同；凭据只在内存比较，未持久化值或摘要。SQLite只读访问可能维护SHM读标记。

私有`checked-002/manifest-check-private.json`首次具有完整schema、输入/证据/配置/源码及scope/policy摘要、明确run_id、cap和绝对deadline。默认check未创建结果根或真实账本意图；`launch_ready=false`。同时保留不可执行的`bound-recipe-private.json`作为绑定索引，不能直接启动。已生成的240秒deadline仅服务本次check，过期后不可重放；将来变更live会改变policy/evidence/config身份，必须重新审阅、核对原账本并生成新清单，不得只翻转布尔值继续用旧文件。

## 实际Linux合成运行

代码改动后新建独立`source-initial-reviewed`闭包，复用既有固定node/pi树，无下载/升级或镜像重建；code/controller/worker指纹已更新，其余固定runtime指纹相同。只读在线核对Docker daemon与缓存镜像身份。实际两槽使用300KB合成报告元数据，初始帧322177/322306字节，超旧上限且小于新上限；原完整report身份通过worker和宿主验证，模型请求未因该元数据改变。

两槽各新会话、合同有效，HTTP各403/403/200/403，进程退出0；MockTransport仅2次，两笔合成结算各834微元。每份私有usage诊断1468字节，权限/单条JSON/计量及槽位结算关联检查通过；2DONE/28NOT_RUN。两个容器均删除，按精确operation标签查询无残留。没有把真实输入发给MockTransport，也没有把合成账本用于真实余额证明。

## 验证与边界

完整Pi离线2024 passed、0 skipped、19项pi_lab/pi_live未选入（56.84秒），compileall和diff-check通过；未运行业务Python/Go/web或完整设施CI。真实provider响应、缓存usage语义、提供方账户余额与账单、产品语义质量及生产部署均未验收。本轮仍是已绑定、可核查的准备结果；下一步是重新生成明确放行的有界真实诊断配置并核对响应及账单，原累计20元限制和历史unknown继续有效。

私有脚本、初次阻塞日志、修复前后回归及完整check清单保存在忽略目录`.local/pi-real-input-binding-20261022/`，Linux原始证据仍在`.local/pi-analysis-launcher/actual-initial-001/`；公开只保存无正文结果与摘要。首次失败未被覆盖。

## 独立审查

审查474d038相对fb350da的本轮完整变更，Critical0、Important0、Minor0；独立93项相关测试通过（4.97秒）。初次沙箱禁止本地TCP/Unix socket造成8项受阻失败，不计为通过；获准重跑同组后全部通过。17项证据摘要、三份来源摘要、当前源码闭包及完整离线JUnit核对一致。

审查者未直接读取真实凭据/原账本/策略/原输入，未额外调用Docker或提供方。执行者接受此审查边界：原状态保留依据本轮执行者实际字节比较及只读audit，实际容器生命周期/清理依据执行者运行与最后精确标签查询；错误时需重查保留性或重跑隔离验证。真实计量、账单、语义质量、发布及未来live配置仍不作验收声明。首帧上限选择的代价是最多额外约320KiB可信输入缓冲或继续拒绝更大报告，未换取relay或HTTP边界放宽。无延期Minor。
