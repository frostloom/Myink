# 首次 main 与 Pi 管理台服务器发布清单

当前状态：待用户明确批准。此清单不是发布完成回执。

发布源代码冻结为 main/controller `096282508aabad61d0f7dcd883b52c36ffa7e3eb`。产品镜像来自 `be306a459447a148f5393391c7fb15a9d4f4aef9`；两个提交的 src/myink、web 与 Caddy 产品代码没有差异，096只增加宿主交接、测试与文档。产品与控制器版本分别记录。

[main 精确 CI 全绿](https://github.com/frostloom/Myink/actions/runs/41185303069)，[Pi 精确 CI 全绿](https://github.com/frostloom/Myink/actions/runs/41184072461)。本地完整 Pi 离线4531项通过、63项专用/真实调用测试未执行；独立审查3项问题已用失败用例修复。[交接验证](pi-manual-main-handoff-2026-10-31.md)区分了模拟与真实证据。

## 精确材料

- 产品归档 `/private/tmp/myink-pi-main-publication-20261031.tar`，139777536字节，SHA256 `46b1e07b364f9b112c7616162e23eaacb79db7f5f4c6c9ff8662f03a80831e9f`。API config摘要 `056d15bfe4bb3c1593526d3d2413c4d9cb26ebb5925c77cc2ad5e4d42f0ad267`，Caddy config摘要 `b34dbdf426b2805cd360097a8b034b621f4735a26c8d5b9f2f394b6f4907c491`；均为amd64/Linux/UID10001。
- API完整155份Python文件与源提交一致，128条OpenAPI一致，未登录401/no-store。当前前端5文件与三引擎验收构建逐文件一致；额外39份资源直接来自实际旧生产Caddy `04d75d…`，经过哈希冲突检查。44条静态路径及字节、--resume维护配置和503/Retry-After在本地合成HTTP环境验证通过。
- 控制器417文件，runtime pin `1026e83f24948281f891de506cbf0b7384ee7b88b1d441b26890d1c4ecba8311`。归档 `/private/tmp/myink-pi-console-runtime-09628250.tar.gz`，SHA256 `a4ac898e3fc09e3336327389a012dab4f0417062703408306b13535dd87b7879`。
- [机器材料清单](pi-first-main-publication-2026-10-31.json)保留全部静态文件、旧源快照与归档摘要。目标daemon加载后的实际image ID须重新读取并验证config摘要与完整源码，不能沿用本地manifest index充当实际部署身份。

## 已核对的原状态与边界

服务器仍是f230/18b的API和两个worker、旧Caddy04d75d；API/Caddy及依赖服务健康。PG约30.8MB、剩余磁盘约13.8GB。没有native产品发布配置和维护四表，故本次是经批准的人工首次主线更新；不是绕过已接管协议。原周期 `0ad352dc-888b-4a75-97d4-39296f327c6b` 仍observing，旧包摘要 `d8c7a9244c15eabb7f59f70eb9fafffb3834be49893c28bcb41030e9b1e3041e`，部署收据摘要 `897e8beb72f7f7f8b3ab7355a7e80161671bc748fb79751b310217f667b9b9f3`。当前执行中任务0，等待人工任务1；RabbitMQ5队列ready/unacked均0，Redis任务/书锁均0。执行前再次核对，漂移或新增任务不能被忽略或强制取消。

复用原manager、费用、Gate、审计库。累计50元和9笔未知预留不变；本次发布过程不触发Pi模型请求，不重放旧任务或释放未知费用。Root socket只读挂给API，不给worker、模型或浏览器Docker socket、原账本和宿主路径选择权。服务器不持有GitHub写凭据；本次不从服务器推GitHub或registry。

## 一次批准后的执行顺序

1. 北京时间06:00–23:00开工，最多30分钟维护；留出下次02:00前的完整发布后观察窗口。过时、原周期或物理版本改变时先停止重核。上传后核对两归档及Git bundle，加载到实际daemon重新验证代码/静态/平台/ID，保留全部旧镜像；上传和预检不占停机时间。
2. 取得原nightly和maintenance锁；保留旧有效Compose、私有env、容器配置、Caddy运行配置/持久化配置以及费用/manager摘要。关闭真实API入口，核对活动与autosave的503配置一致。自然停止API、排空执行与队列、停止两个worker；不SIGKILL，不取消那个等待人工的任务。
3. 完成PG和反馈附件的可恢复备份。新成品用一次性迁移角色执行幂等初始化，关闭新维护行，在关闭状态绑定精确新身份；旧数据、凭据及持久卷保留。源文件只有初始化演练证据，真实迁移必须保存本次前后回执。
4. 安装独立root桥接与可信Git对象库，先只读配置；验证systemd、Linux peer及UID10001读取。合并原有效配置与显式console override，仅替换API/双worker/Caddy，新增API只读socket挂载和provenance。新Caddy以--resume保留外部503围栏，PG/Redis/RabbitMQ与数据、证书卷不替换。
5. 核验新实际镜像、健康、原业务环境/挂载、主线页面/旧资源、完整Python包、PG维护身份及指标源只读role/views；恢复PG准入时仍保持外部入口围栏。检查401、socket身份及原账本不变，绑定新profile、固定模板、nightly env与同一controller pin。
6. 用独立root批准和真实新身份完成元数据交接：先导出审计、持久化verified，再最后结束旧观察为interrupted/insufficient_evidence；旧包、批准、部署、任务及已有失败不改，不写比较通过。交接入口自行重新取得两把原锁，不在外层嵌套持有它们。
7. 恢复并验证外部入口。桥接权限与审计核对后启用固定候选发布配置；这不批准任何未来候选。Pi继续原50元范围的夜间工作，未来镜像仍须管理员逐轮点击确认；几天不确认就持续等待。

未知结果保留围栏与原意图，停止自动动作。可明确核验时按保留的旧镜像/完整配置回退；不自行恢复已经接纳新业务后的数据库、不改费用库、不改UUID重放。发生实际失败仍须留下回执和当前真实状态。

ACTUAL Linux/systemd/peer、真实主线切换及本次观察交接尚未执行。当前旧版本最新真实窗口仍为0合格样本、证据不足；本清单不宣称线上改善或完整闭环完成。
