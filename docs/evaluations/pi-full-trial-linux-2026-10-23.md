# Pi 完整对照模式：真实 Linux 容器合成验收

2026-10-23：已使用真实 Linux ARM64 Node24.22.0 / Pi1.1.0、固定既有镜像和当前生产 launcher/provider/worker，完成完整30槽和三个停止场景。外部HTTP全部替换为MockTransport；本轮34次合成请求、34个实际容器均核对清理完毕，真实付费请求为0。生产代码本阶段没有修改。

## 结果

| 场景 | 最终30槽状态 | 合成请求/所属容器 | 合成账本与清理 |
| --- | --- | --- | --- |
| 完整对照，前三槽分别目标域违规/非法JSON/无效schema | 27 DONE、3 FAILED、0 NOT_RUN | 30 / 30 | 30笔known，共25020 microyuan；30个不同session，各403/403/200/403；所有容器exit0并删除 |
| 第一槽普通失败，第二槽模拟上游读取失败/usage未知 | 1 FAILED、1 UNCERTAIN、28 NOT_RUN | 2 / 2 | 第一笔known834，第二笔unknown全额保留19384 microyuan；停止后续，两容器删除 |
| 空assistant输出 | 1 UNCERTAIN、29 NOT_RUN | 1 / 1 | known834保留；引擎/会话验证拒绝，未伪装普通FAILED，容器删除 |
| 原严格pilot遇目标合同失败 | 1 UNCERTAIN、29 NOT_RUN | 1 / 1 | known834保留，未前进，容器删除 |

这里的DONE只代表通过原输出合同及宿主边界检查；FAILED是确定的输出不合格。模拟响应由验收脚本预设，27/30不是模型表现或写作质量指标。empty-output和pilot槽虽UNCERTAIN，其对应model-attempt仍为known/done：输出状态不用于抹掉已知费用。所有金额均按固定合成usage和虚构费率计算，**不是真实消费或账单证明**。

公开summary按两臂/五组保留完整分母；mixed场景baseline15槽为13 DONE/2 FAILED，candidate15槽为14 DONE/1 FAILED。这些数量只是预设协议控制，不能证明candidate优于baseline。

## 环境和证据

- 显式核对原本机daemon及固定缓存image身份，不pull/build、不改Docker context或其他服务。所有容器保持network none、uid/gid65534、只读根、capdropALL、no-new-privileges、384MiB/0swap/.5CPU/64pids；复用原可信宿主精确归属清理。
- 新建独立source快照：node/pi通过只读使用的硬链接树复用已核验固定依赖，当前完整生产源码独立复制；不修改历史source、凭据或账本。运行时规范指纹仍为6e169d5462405f59c070365267eec24fddc005a3c141819ba7a1f548a592c528；各场景执行前后重新核对完整运行时/代码闭包一致。
- 原生产_provider函数保持不变，仅httpx外部wire被模拟，外部目标限定；其他HTTP目的地拒绝，宿主socket连接仅允许127.0.0.1。容器无外部网络；真实输入、provider key、canonical ledger均未读取或挂载。
- 默认check的账本字节保持不变，未创建结果根；实际执行分别创建全新独立合成run和账本，未重发旧槽或重置历史run。
- 验收结束后独立复核四份回执SHA、所有30槽分母、known/unknown模拟费用和每个operation精确label为空；再用项目Python3.12只读SQL直接核对四个合成账本的槽状态与model-attempt终态，均与回执一致。
- 首次脚本准备因误用Path.open(opener=...)失败，尚未创建run或容器；原脚本、日志及source保留。修正为open(path,...,opener=...)后在全新attempt-002执行成功，没有改生产代码或绕过门禁。

[机器记录](pi-full-trial-linux-2026-10-23.json)保留当前源码与运行时指纹、各operation、脱敏汇总和原回执/脚本摘要。完整合成证据位于当前worktree的`.local/pi-full-trial-linux-20261023/attempt-002/`；独立脚本在其父目录acceptance.py。证据不提交。

## 结论边界

本阶段补上上一阶段的真实Linux运行时验收；未新增生产代码，所以没有重复运行未变化的2156项离线回归，上一阶段的2156 passed/19 deselected/0 skipped仍只对应当时代码和离线测试。根产品PostgreSQL/Redis/RabbitMQ集成、本轮真实provider效果/usage/账单和语义质量仍未验收。production_ready、billing_verified、automatic_execution、release_allowed仍false。

代码与报告均保留在codex/pi-autonomy-design工作区，未提交/推送、未合并main或部署。若后续进入真实模型对照，应另行审阅当前源码快照、私有输入、价格与预算/期限；不能沿用本合成清单作为付费授权。
