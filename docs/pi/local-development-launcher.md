# 本机受控 Pi 开发入口

`python -m ops.pi.development_launcher` 将本机 Linux Pi 开发流程组织为可重复的有限执行。宿主冻结任务、源码、测试和独立审查；Pi 只能通过受控工具修改候选。结果先留在私有候选目录，由宿主审查采纳，不自动修改工作树或执行 Git 操作。

## 使用

配置必须是绝对路径，文件600、父目录700。默认仅预检：

```sh
python -m ops.pi.development_launcher --config /absolute/private/config.json
```

预检不创建输出目录、账本或锁，不启动 Docker，也不调用模型。账本必须存在、已落盘且没有活跃 WAL；预检用 immutable 只读连接并比较读取前后的主文件/WAL 状态，拒绝忽略尚未落盘的数据。若其他账本用户仍在运行，等待它正常结束后重新冻结检查点，不删除 WAL/SHM 文件。

宿主已取得对应数据外发、付费范围和独立审查授权时执行：

```sh
python -m ops.pi.development_launcher --config /absolute/private/config.json --execute
```

执行取得原账本 `.tools.lock` 排他锁并重新验证相同配置，创建全新私有输出根，将完整源快照复制成候选。真实费用始终进入原账本；受控工具使用单独 `tools.sqlite`，避免与费用锁自锁。模型调用临时启用，结束按相同字节条件恢复；策略发生外部变化时拒绝覆盖并报告失败。

退出码0只代表当前模式的成功：预检为 `ready`；执行须 `verified`。详细回执保存在私有输出根的 `result.json`；CLI 只打印简短结果。不能用一条历史成功命令再次执行：输出根已存在会拒绝，失败/未知调用也不重放。每个新任务都要有新身份、最新账本检查点和独立绑定。

## 冻结配置

schema 为 `pi-development-v1`，未知字段和重复 JSON 键拒绝。完整字段见 `ops/pi/development_inputs.py::FIELDS`：

| 组 | 字段及要求 |
| --- | --- |
| 身份 | `schema`, `run_id`, `root`；root不存在，父目录700，与输入互不重叠 |
| 完整源码 | `source_path`, `source_sha256`；根仅含src，完整依赖树摘要，普通单链接文件，拒绝符号链接/特殊文件 |
| 固定运行时 | `runtime_path`, `runtime_sha256`；根仅有node/pi/code，Linux ARM64 Node、Pi1.1.0、完整依赖及当前控制器源码一致 |
| 原费用账本 | `ledger_path`, `ledger_sha256`；逻辑operations/events及scope的只读检查点，原审批与策略限额匹配，不创建scope |
| 关闭策略/凭据 | `policy_path`, `policy_sha256`, `credential_path`, `credential_sha256`；600文件/700父目录，live与server_daily都关闭，提供方身份一致；内容不进公开报告 |
| 任务与基线 | `plan_path`, `plan_sha256`, `baseline_path`, `baseline_sha256`；完整Plan字段及既有确定性规则、配对数量、范围与执行限额一致 |
| 独立审查 | `review_path`, `review_sha256`；宿主提供真实独立批准，绑定下述身份，模型不能自批 |
| 固定检查 | `test_path`, `test_sha256`, `test_cases`；Python unittest，精确完整case ID列表，模块名固定为fixed_development_tests |
| 隔离平台 | `docker`, `endpoint`, `daemon_id`, `image_id`, `checker_image_id`；绝对真实可执行路径、本机unix端点、daemon及不可变镜像ID |
| 有限执行 | `max_requests`, `max_tools`, `deadline_seconds`；建议30/64/900，工具计数包括回执核验；程序上界100/256/1800，Plan估计不能超出 |

`authorization_sha256` 是配置除 `review_path/review_sha256` 外全部字段的规范摘要，避免递归。审查工件必须含 source=independent_review、verified=true、result=approved、真实reviewer，以及 authorization_sha256、plan_hash、base=完整source摘要、candidate_id=run_id、owner=local-development-controller、generation=1。reviewer不能是model或owner。入口校验绑定，不把模型文字转换成批准；审查者的实际判断由宿主负责。

运行时 `code` 是当前ops/pi非tests/非缓存文件的完整快照，不能夹带别的导入文件。源码、测试、Plan、策略、账本变更均需新的冻结记录；凭据只由宿主HTTP客户端读取，容器没有真密钥、费用账本或Docker socket。配置本身可能包含私有路径，应保持私有。

## 执行与成功协议

Pi 容器无外网、非root、根只读、capabilities全移除、no-new-privileges，384MiB内存且无额外swap、0.5CPU、64pids；仅固定worker/runtime两项只读挂载和有限tmpfs。有限stdio中继只处理模型、固定工具和回执核验。候选检查器是独立同类隔离容器，仅挂载当前src副本和固定测试；宿主不import候选。 静态审查也不得通过sys.path、importlib或exec_module在宿主做额外动态复现；新增边界需要独立隔离checker及冻结测试。精确摘要审查采纳后，普通产品回归才针对工作树运行。

一次成功必须满足真实非空补丁、最后补丁之后固定unit全通过、此后candidate_status绑定同一候选、Pi退出后的工具/会话/RPC认证、全部拥有容器删除。每次检查器都登记到执行级清理；任何清理异常即使后来恢复，也不能让本轮报告成功。原账本行与事件前缀保持，未知费用保留。检查失败、取消、超时、未知费用、调用上限或缺失终态均不能被当作成功。

模型每次apply_patch只传一个edit对象，多次修改用最新候选和源哈希；至少为unit→status→final保留请求空间。普通unit失败以仍为blocked的认证check_feedback返回固定失败用例ID、已知错误类别和宿主允许的属性名，未知属性映射unknown_attribute；不向模型发送原始traceback或任意诊断文本。Pi可在同一活跃受限会话内依据反馈修改、复检，最后仍须实际PASS后status。详细受限日志保存在私有检查目录。 Docker合并stdout/stderr不保证跨流顺序；宿主从有界输出中提取唯一、字段完整的JSON报告，再校验固定库存、计数、真实退出码与清理。报告缺失或重复仍拒绝，不以日志最后一行或模型文字判定通过。类级初始化失败、subTest或同一用例多重failure/error等当前无法精确表示的形式拒绝分类，不静默丢弃计数或判通过。异常附加备注可能令诊断类别退化为RuntimeError，不影响失败门槛。固定测试与精确库存提供普通工程证据，不证明对主动篡改测试运行器的候选有语义防伪；实际补丁仍需独立审查。

这是本机宿主监督的有限开发入口。完整产品回归由宿主独立测试服务执行；不自动合并、部署、发布，也不启用服务器长期自治。费用是原账本按冻结费率记录的用量计量，不等于独立核对过的服务商账单。

补丁参数错误也可在当前活跃会话内纠正：develop 的 apply_patch 仅在 Pi SDK 本地使用固定对象路由壳，发往模型的严格 schema 和宿主实际执行 schema 均保持原样。额外字段、遗漏字段或错误嵌套类型原样到宿主后产生严格拒绝回执，源码不变。只有这些原始坏参数与当前宿主完整 blocked 回执精确匹配，网关才允许它们作为失败历史进入下一模型请求；本地错误字符串、伪造/旧会话回执或成功状态都不能替代。新补丁必须用新call ID重新通过原完整校验，不补写旧调用或恢复终止会话。

## 本机维护任务接力 API

`ops.pi.maintenance_handoff.run_local_development` 提供单轮分析 → 宿主冻结与独立审查 → 现有开发入口执行。输入为控制账本路径、cycle_id、宿主已复现任务目录、预期计费账本路径，以及可信宿主分析/冻结适配器、当前来源身份查询、单调时钟绝对deadline和共享cancel。它不创建模型预算，不自动采纳代码、执行Git或发布。

目录每项固定task_id、problem、source/evidence/test SHA、files、test_cases及失败库存。`baseline`包含tests/cases/failures/errors/skipped/failed_cases/error_cases，至少一项真实失败且错误/跳过为零；必须来自宿主隔离检查器，不能由分析模型自称已复现。整个目录共用一个source SHA，有界且深拷贝传给分析适配器。

分析适配器应以无工具Engine执行并认证结果，返回绑定当前operation_id/input_hash/mode的可信Receipt；proposal只能包含task_id/source_sha256/evidence_sha256/reason。task_id为null、两个SHA也为null时表示本轮观察、不进入开发。模型不能新增任务、提供配置路径或批准计划。

冻结适配器应在分析之后建立全新配置、原账本最新检查点和具体独立审查，返回config_path及文件config_sha256。完整开发基线的`reproduction`字段必须与目录失败库存精确一致，其余Plan所需字段保留。协调器重新执行现有预检，匹配source/test/cases/files/失败库存/预期计费账本，确保开发相对时限不超过本轮剩余时间；这一步没有通过就不会执行开发。

ACTUAL固定调用现有execute，并传入expected_authorization_sha256和共享cancel；SIMULATED必须显式注入模拟执行器，结果一直标模拟。可选expected_authorization_sha256在启动器产生锁之前校验，默认None兼容旧调用；它绑定授权身份，不包含review_path/review_sha256。冻结文件的config_sha256另行校验，启动器取锁前后完整配置摘要核对仍保留。

控制账本与计费账本在构造Ledger及写claim前排除同路径、链接和同inode，冻结后再次核对。cycle和各阶段都原子claim并持久记录；相同cycle已完成直接返回原结果，pending或未知不重跑。同id换目录、模式或来源视为冲突。不要把新cycle_id当作故障自动重试接口，未知操作须另行人工/可信宿主核对。

所有宿主适配器必须协作遵守统一单调deadline/cancel。共享Timer覆盖接力，身份回调及业务验证后也重新检查；这不是对任意阻塞Python回调的强制终止保证。开发结果必须认证成功、同一run/授权、明确新增未知为整数零、策略恢复、原历史保持及全部所属容器删除。审计失败或未知计费持久保留uncertain及原结果；成功仅返回`next_action=review_candidate`，最终独立代码审查、采纳和完整产品回归仍需现有宿主流程。

该API离线验收之后，已新增下述真实分析与冻结适配器，并完成[真实整链与产品验收](../evaluations/pi-live-handoff-2026-10-24.md)。没有新增付费启动CLI，也未启用服务器长期调度；离线模拟与真实费用/权限仍严格分离。新增ops代码后，每次真实运行必须冻结当前完整runtime，不能复用旧闭包成功回执。

## 真实分析与冻结适配器

`SelectionAdapter(config_path, config_sha256)` 使用 `selection_launcher` 的独立无工具入口，只有固定模型路由，没有工具或回执核验路由。分析配置为 `pi-maintenance-selection-v1`，绑定私有新目录、来源、完整运行时、目录文件、原费用账本、关闭策略、凭据摘要及具体独立审查；最多一次请求、120 秒。只读 `selection_launcher.check` 不产生输出目录或调用。宿主核对实际请求、固定 system/cwd、停止后 system/user/assistant 三条会话消息及逐条有序 RPC、clear/abort、退出及容器清理。已知费用但选择格式不合格为 blocked；无法证明执行或费用则保持 uncertain。

`FrozenDevelopmentAdapter(templates, root, billing_ledger_path, reviewer)` 仅从宿主 task_id 映射读取模板。分析后刷新原账本检查点、缩短期限，生成全新 `review-request.json`，通过 `FileReview` 有界等待外部独立审查，再完整预检。模型不提供路径、不写审批、不生成预算。ACTUAL 仅接受 `FileReview`，禁止用自动 callback 批准；SIMULATED 必须显式注入模拟传输和开发执行器，结果保留模拟标记。

分析关闭和清理只取消本阶段，不能误取消父周期；父取消仍传入。整个协调器仍只返回 `review_candidate`，不采纳代码。固定测试通过后仍须独立静态审查和精确摘要采纳；如果发现语义回归，保留该轮费用和候选，冻结新增边界测试，在隔离 checker 复现后建立新身份，不能重放终止会话或复用旧审批。


## 源码历史的SDK格式

请求中旧版本源码的省略同时支持固定SDK的canonical JSON字符串与单文本块数组，并保持各自表示。两种格式都必须通过同一组原回执、会话、绑定、路径、范围、行数和版本一致性检查；仅修改发给模型的clone中旧`evidence.text`，不修改持久session、宿主回执、最新源码或工具权限。无可信新版本、同版本重复读取或任何失败/不一致历史都不因此获得省略许可。它不保证任意长任务低于64KiB，未知或仍超限请求继续拒绝，不能以投影代替范围/费用审批。[验证记录](../evaluations/pi-wire-history-shape-2026-10-24.md)。


## 工具预算计数（2026-10-26 实测）

`max_tools` 限制的是共用的宿主桥接RPC：`/v1/tools` 工具请求与 `/host/verify` 认证请求都计数。通常一次逻辑工具调用需要一次工具RPC及一次认证RPC，因此 `max_tools=28` 并不代表能完成28次逻辑调用；被拒工具也可能消耗相应额度。规划时应计入最后的固定检查、补丁后 `candidate_status` 及其认证。这次历史失败时函数索引仅提供导航，尚未强制限制读取或预留收尾额度。见[本轮真实失败验收](../evaluations/pi-capability-trial-2026-10-26.md)。


## 开发硬预算（2026-10-26）

开发启动器现在固定限制单次源码文本4096、同绑定累计12288个 `canonical(text)` ASCII JSON字节；跨文件／重建broker／补丁不重置，精确同call回执不重复计源码额度。预算不是完整外层请求大小，原64KiB仍生效。

新开发配置 `max_tools` 至少12，仍与认证RPC共用总额。余量恰10时首个新读取可得到一次认证blocked警告并留下8；之后读取或余量不足10直接停止。收尾模式只允许尚有后续空间的status、patch、unit，最终认证协议不变。幂等旧call原回执照常返回。此机制保留完成路径的额度，不能保证模型修复正确、操作顺序正确或剩余时间足够。详见[硬预算验收](../evaluations/pi-read-completion-budget-2026-10-26.md)。

## 私有任务包草稿

`ops.pi.task_package` 固化复制候选、冻结固定测试和列出静态用例提示的准备步骤，供宿主组织后续小任务。它不解析旧成功/失败回执为新授权，不调用模型、Docker或Git，不创建预算，也不修改产品工作树。

```sh
# 默认只读，只说明输入可以冻结为草稿
python -m ops.pi.task_package --request /absolute/private/package-request.json
# 显式选择一个全新的私有输出目录后才复制
python -m ops.pi.task_package --request /absolute/private/package-request.json --freeze
```

请求是600文件、父目录700，schema=`pi-task-package-v1`，恰含以下字段：

|字段|要求|
|---|---|
|`task_id`, `problem`|宿主提供的有界任务标识与已观察问题；不是审批或新的运行身份|
|`source_path`, `source_sha256`|完整冻结源根仅含src，完整树摘要；拒绝链接、特殊文件及超限源|
|`test_path`, `test_sha256`|600固定Python unittest源、父目录700，最多1MiB、单链接普通文件及精确摘要|
|`files`|1..8个不重复、实际存在的src内相对路径|
|`root`|绝对、无链接、不存在且父目录700的私有输出根；不得与任何输入重叠|

JSON未知字段和重复键拒绝。请求本身最多1MiB。默认检查不创建输出目录；显式冻结排他创建root，复制完整源到`source/src`、测试到`test.py`，所有输出目录700、文件600；前后重验输入和副本摘要。`task-draft.json`先以私有临时文件完整写入、同步并关闭，再通过排他硬链接原子发布最终名称；同名文件不会被覆盖。发布前失败可能留下私有未完成目录，应检查错误并选择新目录，不能覆盖或把同目录当恢复入口。若完成发布后的临时别名清理失败，完整草稿已经提交，返回`staging_retained=true`并保留600私有别名；这仍不构成执行许可。

草稿schema是`pi-task-package-draft-v1`，包含来源摘要、声明文件及`test_case_hints`，并明确`inventory_status=static_unverified`。提示仅来自AST中顶层类直接定义的test_*方法；不会import测试，继承、动态load_tests或实际加载错误必须由隔离checker检查。提示不是实际测试库存，不构成baseline或语义正确性证明。

后续仍须重新建立隔离基线、全新run/cycle身份及独立选题/开发审查，才能构造现有`pi-development-v1`配置；既有`prepare_template`会直接拒绝草稿schema。绿色基线不能伪装成目录要求的真实失败任务。原候选已通过检查、未通过检查或尚未采纳，均不因此获得自动续跑许可。

新增此类ops代码后，下一次真实Pi执行仍须重新冻结当前完整runtime并绑定新审查；旧runtime闭包或旧批准不能复用。完整功能与无付费验收见[任务包草稿验收](../evaluations/pi-task-package-2026-10-26.md)。

## 草稿到隔离基线

`ops.pi.package_baseline` 接收已冻结草稿，用既有固定checker做一次新的隔离检查，生成真实失败库存及可选题目录。默认仅本地只读验证配置和草稿，不探测Docker可用性；显式执行才启动一个新的所属checker，无付费模型或账本操作。

```sh
python -m ops.pi.package_baseline --request /absolute/private/baseline-request.json
python -m ops.pi.package_baseline --request /absolute/private/baseline-request.json --execute
```

请求是600文件、父目录700，schema=`pi-package-baseline-request-v1`；恰含`schema`、`baseline_id`、`draft_path`、`draft_sha256`、`root`、`docker`、`endpoint`、`daemon_id`、`checker_image_id`和`deadline_seconds`。必须明确本机unix端点、daemon身份与不可变checker镜像，截止时间为1..300秒整数。root不存在且父目录700，不得与任何输入、Docker可执行文件及Unix端点实际路径（含别名解析）重叠。重复输出根拒绝，不自动续跑、覆盖或删除旧结果。

只接受最终发布的`task-draft.json`及其精确摘要，源码和gold必须位于该包的`source`、`test.py`，当前字节及AST hints仍一致。原始输入可以已归档，origin只保留来源说明、不重新授予权限。静态提示只是期望库存；实际继承/动态库存不符、跳过等仍按原checker拒绝，不能为匹配提示丢弃真实用例。

执行复用原`_fixed_check`和`OwnedHosts`，不在宿主import源或gold。资源收尾后再次核对request/draft/source/gold及实际checker副本，清理异常即使后续恢复也不能合格。取消和截止时间用于检查与收尾后的资格判定；必要的清理必须完成，不能承诺对任意宿主回调强制终止。

最后原子发布600 `outcome.json`，schema=`pi-package-baseline-outcome-v1`。`verified`表示精确库存、0错误/跳过且输入/副本/退出/清理均已核验的基线，**不表示所有断言通过**；`check_passed`单列。只有已复现断言失败、错误/跳过为零才`eligible_for_selection=true`，并经原`_catalog`校验后嵌入`catalog`。绿色基线可核验成功但目录为空。基线库存本身合法而目录因重复库存等超过原60,000字节限制时，仍保存已核验基线，`catalog=[]`、`eligible_for_selection=false`并记录`catalog_rejection`；不调高限制或丢失outcome。运行错误、跳过、库存漂移、取消超时或清理未知均不能进入目录。退出码0表示该模式核验成功，不等于测试全绿。

结果不包含预算、Plan、运行时批准或独立审查；现有开发预检拒绝该schema。宿主可将合格catalog交给现有选题/开发流程，但仍须新的run/cycle身份、当前完整runtime和独立审查。不得把新root当未知资源的自动重试，先检查原所属资源记录并完成核对。原checker对恶意候选篡改Python测试运行器的语义限制不变，后续完整代码审查仍然必要。[基线接力验收](../evaluations/pi-package-baseline-2026-10-27.md)。

### 完整本机接力命令

`python -m ops.pi.local_cycle --request /绝对路径/cycle.json` 默认只读，先验证固定选题配置及全部开发模板，检查失败不接触 Docker 或模型；增加 `--execute` 才调用原本的有限 ACTUAL 协调器。配置 schema 为 `pi-local-cycle-v1`，字段为 `cycle_id`、新建私有 `root`、独立 `control_ledger_path`、`selection_config_path/selection_config_sha256`、`templates_path/templates_sha256`、`deadline_seconds`（1–3600）、`review_wait_seconds`（1–600）。全部路径仍须满足原私有输入规则。

入口执行选题、刷新账本检查点、等待独立开发审查、开发并认证候选；控制账本和费用账本各自独立。`root/result.json` 保存原协调器 receipt；`observe` 表示无任务、`review_candidate` 表示候选待独立审查，`uncertain/reconcile` 必须核对费用与资源。已有输出根目录不再执行，不自动重试、不自动采纳候选。底层协调器既有终态重放 API 不变。

可先用 `python -m ops.pi.cycle_bundle --request /绝对路径/bundle-request.json --freeze` 机械生成配置包。请求 schema 为 `pi-cycle-bundle-v1`，包含新建私有 `root`、`cycle_id`、`selection_run_id`、已固定 `template_path/template_sha256`、合格隔离基线 `outcome_path/outcome_sha256`、上述两个期限字段。默认不带 `--freeze` 只检查；只接受与模板源、测试、文件范围和复现结果完全一致的单任务目录。它复用宿主编写的 Plan 和开发模板，不把模型文本变成路径或权限。

独立审查者读取生成的 `selection-review-request.json` 与实际输入，在指定 `selection-review.json` 写入绑定授权摘要的审查结果。再执行 `python -m ops.pi.cycle_bundle --request /绝对路径/bundle/bundle.json --seal`，重新验证原请求、模板、基线、目录及审查，通过完整入口只读检查后排他发布 `cycle.json`。原零审查草稿保留，实际入口引用单独的 reviewed 配置。之后才显式执行 `local_cycle --request .../cycle.json --execute`。开发审查在选题后按最新账本再次独立完成；配置生成工具不生成任何批准。
