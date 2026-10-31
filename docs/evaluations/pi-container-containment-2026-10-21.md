# Pi 当前Mac容器底座隔离验收（2026-10-21）

范围：在codex/pi-autonomy-design（起点d471f73）验证当前Docker Desktop上的隔离执行底座。使用已缓存Linux ARM64 Python3.12镜像和固定合成canary；不是原Mac Pi进程的隔离回执，也不是完整Pi运行验收或付费grant。`pi_runtime_verified=false`、`production_ready=false`、`automatic_execution=false`、`paid_requests=0`。

## 执行边界

- 明确本地Unix socket、实际daemon ID和不可变镜像ID（不pull、不build、不改共享daemon/VM配置）。每个探针独立UUID、固定模式容器，串行执行；不动业务容器、其他worktree或固定myink-test。
- `network=none`、uid/gid65534、只读根、cap-drop ALL、no-new-privileges、独立PID/cgroup命名空间；memory384MiB、swap0、CPU0.5核、pids64。只挂载固定探针和合成source（只读）；可写/tmp、/work均为小型noexec/nosuid/nodev tmpfs。
- 无真实源码、账本、凭据、真实会话、宿主socket挂载；不继承模型凭据环境。不提供模型HTTP转发。受认证loopback服务只是容器内正对照，测试200/403；它不表示已将宿主预算网关接入Pi容器。
- 资源压力前检查Linux VM MemAvailable至少512MiB，最多384MiB/0.5CPU、串行短探针。超时/输出溢出先停止所属容器PID1，再退出attach客户端；只有确属新UUID、镜像、容器ID/名称/标签与原daemon的对象可以停止/删除，不按前缀或标签批量清理、不prune。

## 实际证据

四类探针：

1. **隔离**：先证实合成source可读、tmpfs可写、loopback认证成功；随后检查source/harness不可写、未挂载私有canary和别名不可读、凭据环境及宿主socket不可达，直接/嵌套网络不可用，uid/gid、NoNewPrivs、CapEff正确。
2. **资源**：读取实际cgroup文件，同时观察CPU节流、超额内存子进程OOM终止、PID上限拒绝；不能只凭Docker参数认定生效。
3. **总期限**：固定父/子/孙进程，子孙均setsid脱离原进程组且忽略SIGTERM。2秒后SIGKILL容器PID1，核验停止PID=0、退出137，并删除精确容器；不只杀Docker CLI。
4. **输出溢出**：同样先建立detached子孙，输出超过65536字节即停止整个容器；保留不超过65536字节的私有原始前缀。该上限是探针I/O上限，不能冒充Pi分析正文32768字节合同的验收。

最终真实运行actual-005为4/4通过，4个容器均停止并删除；[公开机器回执](pi-container-containment-2026-10-21.json)保留完整指纹和合成测量。原始失败与成功记录保存在忽略目录`.local/pi-containment/`，公开JSON仅投影合成证明、资源测量、状态、数量和哈希，不含原始正文或密钥。

## 保留的失败与修复

- 初始测试缺模块RED：18 failed/13 fixture errors，均为预期的missing API断言；首次GREEN31 passed。
- actual-001：操作者首次填写错误镜像ID，缓存身份检查拒绝，未创建容器；保留blocked回执。
- actual-002：隔离canary全部通过，但Docker `ps`核验过滤器缺`label=`，rm已执行后确认命令失败；整体正确保留blocked。独立只读label查询确认无本轮残留。修复前先把真实错误和清理失败丢失分项证据加入回归，6 failed/26 passed → 32 passed。
- actual-003：四类均通过；实际memory.max402653184、swap.max0、cpu.max50000/100000、pids.max64，memory.peak402653184、OOM kill增加1、节流增加21、PID上限64时拒绝；超时/溢出均观察到3个所属进程，四容器停止/删除确认。
- 创建取消边界：KeyboardInterrupt可能发生在daemon已创建、客户端未得到ID之间；先复现1 failed/37 passed，再通过精确名字、新UUID标签、镜像恢复归属并清理；38项定向通过。daemon漂移、foreign标签/ID/镜像保持拒绝，不误删。

## 后续与限制

当前Mac已有Node24.22.0/Pi1.1.0；Pi包声明Node>=22.19.0，缓存Linux Node20不满足，Mac Darwin二进制也不能充当Linux运行时。本轮没有拉取新镜像或安装包，没有启动真实Pi。下一步准备匹配的Linux Node/Pi版本，在这些隔离边界内接入当前预算网关并做真实Pi的本地合成验证；还需要可信loopback代理通道、固定会话/运行身份与无工具验收。

本回执只适用于本次合成Python容器底座及记录的daemon/image/worker/controller指纹，不返回`accepted_envelope`，不可转成Pi付费运行许可。它不验收checker隔离、重任务聚合限额、生产部署或服务器容量；旧WSL证明不自动迁移。原累计20元账本、未知预留和45项unknown语义指标保持不变。

## 最终复核

独立审查发现并用受控runner复现两项异常边界：create超时后daemon可能迟到创建对象；同步docker top原15秒超时可能越过2秒执行期限。新增回归先得到3 failed/38 passed，修复后41 passed。创建前保留精确待确认name/mode，异常及finally分别核对归属；无法确认时保留daemon/image/operation/name身份并记录UnresolvedCreate和blocked，不能将即时not-found解释为最终无残留。foreign对象仍不得清理。top及EOF后的等待使用剩余执行期限，超时先停止所属命名空间。

actual-005操作ID为e2b98fbd-6a2a-4209-a716-44c34e824775；controller指纹b521f683d4fb4015b0e4b76b6edf8cfd49007f1e10f19d16cf7208db5ca7eac3，worker指纹5facf516a4380b8e8d8e02f101027d381cb954691b32267855246f748f2038fb。隔离通过，资源实测memory.max/peak402653184、swap0、cpu.max50000/100000、pids.max/peak64，OOM增加1、CPU节流增加21，PID超限被拒绝。timeout与overflow均观察到3个所属进程，最终退出137；溢出原始前缀严格限制65536字节。

2秒为执行监控期限，停止和Docker控制操作仍有额外开销：此次timeout总观察2.353秒，overflow1.167秒。daemon不可用时无法保证宿主硬实时终止，清理无法确认必须blocked；不将此当成独立于daemon的硬看门狗。迟到create若在有界核对后才完成，仍需要使用保留身份后续恢复，绝不报告已确认清理。

最终完整离线回归：1850 passed、0 skipped、19 deselected（pi_lab/pi_live），43.72秒；compileall通过。独立只读复审41项通过，无剩余Critical/Important/Minor；真实actual-005由主代理执行，审查者未操作Docker。另行只读精确operation label查询为空。业务Python/Go/前端与集成服务未运行，本轮未修改这些路径。
