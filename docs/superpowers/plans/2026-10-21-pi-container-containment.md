# Pi 当前宿主容器隔离验收计划

> **For agentic workers:** 使用 executing-plans 内联执行，TDD，最后 requesting-code-review 独立只读审查。用户已授权下一步、提交推送和myink记忆；不合并、不部署、不发付费请求。

**Goal:** 在当前Mac Docker Desktop上实际验证可供Pi使用的隔离底座、资源限制、超时/输出溢出与整个PID命名空间清理，保留可核对证据。
**Architecture:** 新增可信宿主专用 container_probe.py 和固定合成 worker。宿主显式指定本地Docker socket、daemon ID与已缓存不可变Python镜像ID；每次全新UUID独立容器，network=none、只读根、65534用户、cap-drop ALL、no-new-privileges、私有PID/cgroup命名空间，384MiB/0swap/50%CPU/64pids，有限tmpfs。只挂载固定只读探针与合成source；不挂载真实源码、私有账本、凭据、会话或Docker socket。按顺序验证负例、实际内核资源行为、超时及输出溢出，停止后核对容器状态并只删除确属本轮的对象。
**Tech Stack:** Python3.12、pytest、Docker CLI/Engine、已缓存Linux ARM64 Python3.12镜像。
**Spec:** docs/superpowers/specs/2026-10-10-pi-autonomy-design.md资源/隔离边界；docs/HANDOFF-2026-10-20.md当前宿主需重验；用户确认的下一步。

## Global Constraints

- 起点d471f73，仅codex/pi-autonomy-design worktree；保护main/admin未提交改动。
- Docker Desktop是共享daemon：不改daemon/VM配置、全局网络/镜像、业务容器或固定myink-test；不prune、不按前缀批量删除。
- 本轮无镜像pull/build，无外部模型或真实账本，不继承宿主凭据；只运行固定合成探针。
- 原20元scope与未知预留不变；不生成付费grant或可复用Pi acceptance。
- 既有Mac Pi1.1.0需要Node>=22.19；缓存Linux Node20不满足，不能用Mac Node二进制进入Linux。此轮只验收容器底座，不把Python探针当真实Pi验收；下一阶段准备匹配Linux Node/Pi并接入本地模拟。
- 有限只读源码canary、未挂载私有canary、正向受认证loopback对照；所有网络负例仅文档保留地址/容器宿主别名，不探测真实生产。
- 每个压力探针最多384MiB/0.5CPU，串行；内核MemAvailable不足512MiB时停止压力测试。

## Review Focus

1. daemon/context漂移、foreign容器或标签不匹配绝不能被停止/删除。
2. 创建/启动/attach失败也可能留下容器；已证实归属后清理，无法确认则报告blocked。
3. 负例不能因脚本本身不可执行而假通过；必须先有合成source可读、tmpfs可写和loopback认证成功的正例。
4. Detached/setsid后代必须与PID1一起退出，输出溢出要停止整个容器而非只杀Docker CLI。
5. inspect声明不是实际资源证据：核对cgroup文件与OOM/CPU throttle/PID上限的行为，内核和配置都匹配才能通过。

### Task 1: 可信容器探针及完整本地验证

**Files:** 新增 ops/pi/container_probe.py、ops/pi/lab/container_probe_worker.py、ops/pi/tests/test_container_probe.py；更新docs/pi/README.md、验收记录。
**Interfaces:** run_probe(root, *, docker, endpoint, daemon_id, image_id) -> body-free dict；固定CLI使用显式四个可信参数，root必须新建。报告分项passed/blocked，paid_requests=0、pi_runtime_verified=false、production_ready=false，不生成accepted_envelope。

- [x] RED：输入/路径拒绝、宿主环境不透传、固定hardening、严格归属清理、daemon漂移、创建/attach/超时/溢出失败、资源/负例证明完整性。独立临时worker本地逻辑测试；Docker命令层使用受控runner，真实验收另执行。
- [x] 最小实现；原工具/预算/Engine协议不改。
- [x] 定向GREEN；已缓存不可变镜像上实际运行隔离、资源、超时和溢出探针，保留失败与清理记录。
- [x] 独立审查；完整offline ops、compileall、diff检查；如当前环境缺失/拒绝明确blocked不算通过。
- [x] 文档与交付记录准备完成；按用户既有授权提交推送、核验远端SHA并写入核验myink记忆，执行结果以交付消息为准。
