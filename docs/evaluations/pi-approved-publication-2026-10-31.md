# Pi 人工批准发布实录（2026-10-31）

用户已明确批准[最终审阅包](pi-publication-review-2026-10-31.md)。**产品和人工门禁控制器现已部署到服务器；完整线上闭环验收仍等待真实后续指标和次日结果。** 此记录覆盖审阅包中的“未发布”历史状态。

## 已执行

- main仅接入获批5文件产品补丁，提交 `f2304a284247ba02e575e08d73cc97a48a5621c9`，已推送。全部146个产品Python文件与获批镜像的包摘要完全相同。没有整体合并Pi或管理员分支。
- Pi发布前交付 `b4d6e29a` 已推送。[main CI](https://github.com/frostloom/Myink/actions/runs/41149223641)全部3项通过；[Pi CI](https://github.com/frostloom/Myink/actions/runs/41149335094)全部4项通过。随后发现的权限修复源码为 `1fd39a011894c8784dff88c483e61743f499b599`，随本记录推送并由CI继续检查；具体后续CI结果见交付回复和审计。
- 2026-10-31 **08:27:33（北京时间）**，使用精确镜像 `sha256:18b53e0a10bd5245740c701c23ed7620d653e60d06b357b36cd941db140b2c0c` 替换1个API和2个worker。没有构建、拉取、重启依赖服务或执行schema迁移；PG、Redis、RabbitMQ、Caddy、原有环境密钥及数据卷保持原状。
- 发布前原业务队列无待处理/未确认消息；发布后物理核对三个进程的镜像、整包源码、启动时间及部署身份一致。`/healthz`和`/readyz`均HTTP200。健康不等于业务质量提升。
- 原生nightly unit确认实际部署，周期 `0ad352dc-888b-4a75-97d4-39296f327c6b` 已进入 `observing`。批准收据摘要 `53c7e66e26637f2144bdb5d36cb73c888def660a2ed12d3761d3fa298dd513d0`，只授权GitHub推送和部署，没有镜像仓库推送授权。

## 已部署产品与首次控制器

| 项目 | 当前值 |
|---|---|
| 业务source commit | `f2304a284247ba02e575e08d73cc97a48a5621c9` |
| 产物包 | `d8c7a9244c15eabb7f59f70eb9fafffb3834be49893c28bcb41030e9b1e3041e` |
| 产品Python整包 | `295ba54b52dfd7c1f607f5eacf614826e2f6ad4e16dc3df0ef2704def406bdd3` |
| deployment ID | `pi-nightly-0ad352dc-888b-4a75-97d4-39296f327c6b` |
| generation / owner | `1 / human-gated-pi` |
| configuration ID | `55de26a20ca189c2de00e0af2c9bc218f71439d97e4ea522952e4a4d85e91ae8` |
| 控制器源码 | `1fd39a011894c8784dff88c483e61743f499b599` |
| 控制器闭合包 | `f280f235950253ddc9526c479eb461522953673e62da1ebe8955de5511faa68d`，410文件 |
| 控制器归档 | `a55aec50e5634a07dea770ee937ef689a1160675ffbf6fa02c3e3f38a2cc269a` |

控制器切换保留旧49版本及前后配置/权限备份。普通manager和review等入口已加人工门禁，原7个定时器保持disabled/inactive；只启用 `myink-pi-nightly.timer`，实际状态active/waiting，无补跑。服务器时区核对为Asia/Shanghai。

原manager/费用账本未替换，逻辑摘要仍分别为 `a588accf16ed7e7b1d3fc5e04709e000924010c6f840586ffbc2d2599ebf1eff` 和 `fe7c37ea1259b0d92d51524d818703a7063a953e54e53b062dbc36b6eb844afb`。累计50元、9笔历史未知预留不变；本次发布、检查及接线新增Pi模型请求0、费用0。源任务仍是原server-owner-002，未重跑原12次模型开发。

## 接线失败与修复

安装前核对发现配置草稿使用的环境变量名不匹配新unit，已修正为PI_NIGHTLY_ENTRYPOINT、PI_NIGHTLY_CONFIG_SHA256及PI_OBSERVER_RUNTIME_SHA256。实际固定路径配置加载和systemd验证通过，旧配置、unit及目录权限已保存。

实际root指标收集复现了审计权限缺陷：新manifest和page为root0600，原Ubuntu所有者读失败。先保留失败，再仅修复固定audit DB/manifest/摘要命名page及本轮指标收据的所有者；不修改源码、产品DB、凭据或配置目录。测试同时拒绝越界路径、符号链接、路径穿越，并接受导出器支持的大于1MiB、最大8MiB的真实清单。新控制器在下一个真实窗口收集后，Ubuntu成功读完整快照。

原健康探针曾误用不存在的/health而得到404；随后按现有/healthz和/readyz检查通过，未因此修改产品代码。上述失败及修复均保留，不能当作Pi自主改进绩效。

- 相关检查41通过；独立审查11通过并指出清单大小P2，作者失败复现后修复，没有重复审查。
- 最终完整Pi离线回归 **4428通过、63按标记未选入，433.15秒，退出码0**。
- 已部署产品的18项冻结回归此前通过，仍不替代明天的独立次日执行。

### 发布后CI依赖审计修复

交付提交6da95cd4的[CI41153028006](https://github.com/frostloom/Myink/actions/runs/41153028006)在前端依赖安全检查失败。本地对官方npm注册表审计复现16项关联中危问题；来源为10月30日更新的[minimatch公告](https://github.com/advisories/GHSA-g3hv-75wg-m249)与[glob公告](https://github.com/advisories/GHSA-3g3m-2fjr-6pw4)，不是新Pi源码或产品运行故障。

仅在Pi分支开发依赖中明确覆盖minimatch11.0.1、glob14.0.2并更新锁文件，不降级ESLint、不关闭审计。全新npm ci后audit为0漏洞；lint通过（9条既有warning），shared207项及Vue809项单测通过，类型检查和构建通过，随后提交 `c750838c80a8c5b20295274241c2751f36e63408` 的[真实CI41155336216](https://github.com/frostloom/Myink/actions/runs/41155336216)全部4项通过，包含Chromium、Firefox、WebKit矩阵。当前已部署产品、控制器和生产前端均不改变；main仍仅保留本轮获批5文件改动，主线依赖同步须在后续main维护中明确纳入。

## 实际指标与次日任务

先前07:29–08:29及07:44–08:44两个真实窗口跨越部署，只能证明接线。随后真实读取 **08:29–09:29** 完全位于08:27:33部署之后的一小时窗口；读取前后物理进程版本相同，运行配置身份匹配。有效样本仍为 **0/最低20**，状态insufficient_evidence，没有线上改善结论。收据摘要 `3d48a054ece965d991bade21505bd912b83be7a9cde22fca8fb7d9ee9e4ef598`。

下一次门禁定时检查：**11月1日02:00北京时间**；实际次日评测到期：**11月1日03:00北京时间**。届时核对真实运行版本，执行冻结回归和一小时只读指标观察；至少20个完整有效样本、无混杂才可关闭本轮。样本不足继续观察；失败保留审计和人工回退建议，不自动部署或业务回退。下一候选仍须重新等待针对精确产物的人工确认。

原生结果预留在服务器本周期 `observation/assessment-*/`、`observation/regression/`、`observer-binding.json`、`deployment-context.json`及版本化审计记录中。后续控制器补充稳定test_id及原审计库/只读导出的自动发布：回归与指标结果分别关联已登记的nightly-regression和nightly-metrics计划，跨天读取也能关联；保留原observation事件，未执行的指标不生成测试结果。

最终60项相关检查通过，覆盖成功、样本不足、回归失败、模拟/真实模式隔离、重复导出和审计失败恢复。独立审查发现“下一槽位绕过未完成审计”P2，先失败复现再修复；任一早期assessment未写收据，后续槽位也停止，不重复采集。单独恢复导出只恢复审计，不确认评测完成。实际次日计划结果仍为null，尚不能把离线契约测试计为真实次日验收。全回归还发现可选export_root未按原观察器默认行为处理的兼容错误，补充失败测试后恢复既有默认值；失败运行如实保留。

本次后续控制器修改以本记录所在提交的nightly_observation源码为准，精确安装版本、闭合包摘要和执行状态由服务器审计记录提供。业务产品仍使用上表版本。最终完整Pi离线回归 **4436通过、63按标记未选入，353.56秒，退出码0**。

## 审计交接

原1001条历史完整保留，准备后1006条，加上两次真实收集及本次批准、部署、失败/修复、版本和次日计划后，发布后首个完整窗口及CI结果入账后为 **1032条、259个run**。快照摘要 `5ccdf527afe0fef7b927b7df281b4055598d3d0f9684b68f5faabe20375b9d36`；普通用户reader读通完整快照。两项次日计划均为planned，结果为null。

原费用/工具/失败、全部4个产品文件范围及controller修复范围分开记录。reader和管理员契约仍在Pi分支，**main管理员页面未接入**；本次仅合入5文件产品补丁。入口见[增强清单](../pi/agent-enhancements.md)、[管理员交接](../pi/administrator-audit-handoff.md)及[输出对照](../pi/management-audit-output-map.md)。

当前已完成实际部署、接线和调度启用；持续线上有效样本、次日结果、新任务实际迭代仍待真实运行证明，目标没有标为完整达成。
