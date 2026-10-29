# Pi administrator audit handoff

This is a read-only integration contract for the future main/admin implementation.
It does not enable the admin UI, change authentication or grant execution rights.
Use `src/myink/pi_audit.py` and `docs/contracts/pi-audit-v1.md`; never query the
billing/manager SQLite databases from the browser or copy their private payloads.

## Required admin views

| View | Reader input | Required interpretation |
|---|---|---|
| Runs and inspection | `runs()`, `events(run_id)` | Show ACTUAL/SIMULATED, domain, time, status and unknown identity |
| Analysis | analysis events | Model summary is an untrusted hypothesis; host counts/gaps remain separate |
| Repair and tools | plan/review/development/tool/test events | Link operation, fixed candidate, review and outcome; proposed is not approved |
| Memory and enhancements | memory/enhancement events, `enhancements()` | Show provenance, availability, bounds and expiry; memory grants no permission |
| Rollback | deployment/rollback events | Require actual deployment ownership and verified recovery; cleanup is not business rollback |
| Next-day tests | `daily(day).next_tests` | Display planned due time and separate actual result matched by target run/test/candidate; null is pending |
| Daily versions | version events, `daily(day)` | Controller, SDK, policy and observed product versions are distinct; unknown stays unknown |
| Change scope | each event's changes | Keep file category/additions/deletions and base/candidate identities; controller changes are not product adoption |
| Cost | analysis/development host counters | Original cumulative ledger accounting only; unknown reservations remain held |

The reader validates the complete append-only chain and content-addressed export
before returning data. Invalid/missing/oversized snapshots must be unavailable,
not silently presented as a successful run or empty history. Use bounded event
pagination; do not import raw sessions, writing inputs, SQL rows, credentials or
host paths into the panel. The export is audit-only, never execution authority.

## Diagnosis and development flow

A fixed metadata observer freezes the source window, identity and cohort hash.
The host verifies receipts and constructs bounded source-bound audit memory.
The no-tool Pi diagnosis may return `investigate` or `no_action`; it cannot
approve code, arbitrary shell, database writes, budget changes or release.
A finite root-approved queue admits at most one model request per evidence
fingerprint. Window refresh, elapsed date and additional audit/memory output do
not authorize another charge. New evidence without a matching fixed permit
creates an investigation record only. Partial claims and new unknown fees stop
further paid diagnosis; the original nine unknown holds are not released.

A later repair requires a source-bound reproducer, independent file review,
frozen baseline/test/candidate, phase-limited tools, fixed checks, candidate
review and independent acceptance. Keep each tool intent/result and failed
attempt. Repair failure is feedback, not authority to expand scope. Product
release and ownership-safe business rollback remain separate gates.

## Status and evidence rules

- A closed known model charge can accompany a failed output contract. Preserve
  both facts; never retry it as though no request happened.
- A pending/uncertain claim cannot be cleared by deleting files, changing the
  run ID, updating a billing checkpoint or acknowledging a new unknown as legacy.
- Rolling windows may overlap. Show each window and its sample count; do not
  add them into daily independent samples or claim improvement from one task.
- Source/controller/policy/cohort/time/expiry bind memory. It is context only;
  the server does not yet have a Hindsight adapter.
- A scheduled test becomes an actual result only after its real due time and
  fixed execution receipt. Previous-day results cannot satisfy it.
- Keep all controller version events and failed rollout records. UI labels must
  distinguish implemented, scheduled, deployed, actually verified and adopted.

Current deployment evidence and limitations live in `docs/evaluations/` and
`docs/pi/agent-enhancements.md`. The overall management loop remains incomplete
until new-task review, repair, authorized product observation/recovery and real
cross-day validation all have their own evidence.

## Historical plans and corrected metadata

A due-today view must include earlier plans whose scheduled_for falls today; daily.next_tests contains plans recorded on that report day, so reading only today misses a previous-night forecast. Preserve its separate actual result. Daily.versions is a history of event contexts, including failed or subsequently corrected metadata; it is not a single current deployment. Show host review/correction events and their corrects_controller_pin_record evidence links. Use the appropriate component version event for the current controller/config view, while retaining original records.


## Independent SDK review and actual cross-day example

New pre-development SDK review events expose only host-projected recommendation,
reason, request count, known charge and dossier evidence. `passed` means a
verified approve recommendation; it does not grant execution or candidate/product
acceptance. `reject`/`needs_evidence` and invalid output remain non-authorizing.
Complete untrusted commentary stays private. This code path is not yet deployed;
its future issuer must publish exact FileReview independently.

The original Oct28 owner002 plan now has a real Oct29 03:02+08 passed offline
result,18/18cases and0modelrequests. Read the Oct28 report's matching next_tests
entry to display its separate result, including actual time and event evidence.
Keep unknown product release identity unchanged; this fixed candidate regression
is not a production deployment or a24–48hour online validation.


## Host authorization and selected-request linkage (source only)

`host.selection_review.v1` is an exact host permission to run one frozen-catalog
selection. `host.selection_binding.v1` is a verified selection analysis with one
original-ledger request and its known charge; `host.file_review.v1` is distinct
host issuance of exact development FileReview. Evidence links keep the original
independent dossier, unbound and derived leases, selection verification and exact
approval separate. Secondary host-review events omit model/cost counters. None
is a product adoption or release event; code remains pending server activation.

Show abstention, partial binding and unavailable completion distinctly. An
original paid result can remain valid while no development permission exists.
Do not infer an authorization from a model's approve text or from an audit event.


## Reproduction and proposed-problem display (source only)

A verified investigation may expose a bounded `details.hypothesis`; label it as an
untrusted proposed problem, never permission. `investigation.reproduction.v1`
test events expose fixed baseline totals/failures/errors/skips and the separate
next action. A failed baseline may be successfully reproduced and eligible for
independent review; it is not a passed candidate or a deployment. Green/error/
no_task/cancelled/host-failed outcomes remain distinct. Frozen tests and full
sessions stay private; execution/adoption authority never comes from audit text.

## Automatic handoff and abstention projection (source only)

A planned `manager.reviewed_handoff.v1` event links the completed isolated
reproduction, independent SDK review config and sealed original-manager cycle.
It announces admission, not successful development. Waiting for selection or
prepared files does not synthesize a successful tool/test/development event.
`host.selection_abstention.v1` is terminal no_change with one verified original
model request and known charge, plus selection-verification/original-lease
hashes. No development permission follows. Re-reading the same receipt does not
append a duplicate charge/event. Partial binding/publication remains uncertain;
never infer completion solely from an inbox or approval file's presence.

## Coordinator grouping and controller history (source only)

`autonomy.coordinator.v1` uses `details.operation_id` for the full research
fingerprint and links `phase_investigation`, `phase_reproducer`,
`phase_sdk_review` and `phase_manager_handoff` receipt hashes when those stages
exist. Its status distinguishes admission, no_task, not_reproduced,
review_rejected, failure and uncertainty. Group `auto-`, `research-`, `repair-`,
`review-` and `select-` run identities by their common first32fingerprint characters;
keep the full operation/evidence hash as the authoritative correlation.

The parent summary omits model/count fields: add only each authenticated primary
SDK analysis/review charge once. `autonomy.controller.v1` is a separate version
context with controller/source-profile policy/SDK identity, never a product release.
Withdrawal retains the exact original manifest privately; unavailable/partial
coordinator evidence cannot be presented as executable or successfully developed.

## Finished-candidate recommendation (source only)

`candidate.sdk_review.v1` is a fresh no-tool post-development recommendation. It
binds the complete final candidate, original source, actual diff, frozen gold,
Plan and matching passed fixed-check copy. Display candidate/policy/SDK identity,
allowlisted approve/reject/needs_evidence and reason, one original-ledger model
charge and complete change scope. Full commentary/source/gold/diff and SDK/RPC
sessions stay private. `passed` means an authenticated approve recommendation;
it does not mean main adoption, product release or verified online improvement.

The host separately reauthenticates stopped session/RPC, exact initial inputs,
original fee history/known settlement and cleanup. A candidate hash selects one
permanent claim under a finite root-approved private parent. Renaming a run or
output cannot replay the same candidate. Expiry/revocation/candidate changes
before forwarding prevent reservation. Missing/invalid/uncertain results retain
their claim and original fee, with no automatic retry. Secondary completion,
version and next-day-plan events must omit the primary review's cost counters.

This role is implemented and offline-tested but has not been activated on the
server. Automatic post-manager scheduling, independent development-provenance
validation and fixed next-day registration still need their own integration.
No release/deployment/rollback success may be inferred from this source contract.


## Actual finite controller activation — 2026-10-29

`autonomy.controller.rollout.v1` version and
`pi.autonomy.finite_deployment.v1` enhancement events now describe the actual
finite8d1802af controller, its source-profile expiry and67controller/config files
(+4659/-129). A standalone main reader has read these exported facts along with
the original actual18/18next-day result. No product release, new paid research or
new candidate is claimed. Newer post-development SDK role/completion code is
source-only until separately verified deployment. The old runtimes, original
fee/manager history and all six timer roles remain separate identities.

`autonomy.rollout.prelock.corrected.v1` links the retained initial lock-busy event;
its exact initial occurrence time was not recorded. Use the correction's
recorded_at, not the prior retrospective emission time as an exact failure time.
Keep both records. No configuration changed or model request occurred in that
initial locked-out attempt. Actual source coordinator ticks can separately report
lock_busy or outside_window without being failed product deployments.

## Candidate completion observation and remaining schedule boundary

New source reaches a fresh fixed candidate review from an actual completed
manager cycle before a cached research fingerprint can end a wakeup. Root
permission is generated from original manager/SDK/tool/fee proof and current
source policy; modelapprove text is not permission. Candidate review outcomes
are retained separately from original admission, including rejected/invalid/
uncertain results and parent-profile revocation. No replay changes the source
claim, original fee history or legacy holds. Completed development config and
old runtime identity are not rewritten for a separately verified current review
runtime. Live parent-profile pin/expiry still gate the new request.

The new source fixed `development_audit` kernel reauthenticates the original
manager/development proof before projecting each controlled tool in durable order,
bounded failed-case feedback, exact candidate diff, final tests and no_release.
Development counters cover development only. Selection binding/abstention and
fresh SDK review keep their own primary charges; parent completion/followup
records omit those counters. Raw arguments, patch, source, gold and model prose
remain private. This preserves failed tool attempts within a reconciled phase.

`candidate.host_completion.v1` links the original manager task to the fresh
candidate recommendation. `candidate.nextday_reservation.v1` is planned only
when root has appended the exact candidate/source/gold/cases/review entry to the
original fixed followup registry and verified its matching env digest. Both old
config preimages and a durable registration intent precede replacement. Partial
pair publication is unverified, never silently repaired or paid again. Original
registry entries and old executed claims are preserved. Existing followup remains
the sole due-time execution authority; it does not adopt product code.
`followup_registered=False` means blocked, not scheduled. A planned record has
no result until an independently linked ACTUAL due-time test exists. Synthetic
cross-day callbacks cannot satisfy that linkage.

`manager.completion_observation.v1` records original stopped, uncertain,
cancelled or abstaining tasks without certifying partial SDK/tool/fee receipts.
Its model/cost fields are null and range_complete is false; its companion is
no_release. Exact partial private receipts remain retained for reconciliation.
This is an observation, not permission to clear unknown fees or replay a task.
The prior8d1802af release excludes these completion hooks. Current finite
1ea1d514 activation is documented below; new actual pipeline acceptance still
remains separate from source/native/deployment acceptance.


Host post-paid reinspection failures have their own durable uncertain completion
and blocked nextday plan even when the earlier SDK recommendation was passed.
Show both stages; the SDK result is not the final host decision. Unknown baseline
counts stay null; code_regression baseline failures use the authenticated nested
reproduction report, not a missing top-level field.

Current source acceptance record:
[2026-10-29 completion](../evaluations/pi-candidate-completion-source-2026-10-29.md).


## Completion controller actual finite activation — 2026-10-29

`autonomy.completion.rollout.v1` and `pi.candidate_completion.host.v1` now mark
finite1ea1d514 host38d193bc/guest620afd95 active, retaining original9b6d4479
Node/Pi dependencies and50CNY/nineholds. Profile63383ce9 expiresOct30 11:27+08.
19source/config changes+765/-26 are control-plane scope, not product adoption.
`autonomy.completion.upgrade_guard.v1` retains two preconfiguration failures;
those records do not mean an applied product version was rolled back. All four
retrospective records explicitly use recorded_at, not guessed occurrence times.
Standalone main reader verified these events and old actual18/18due linkage.
No new paid pipeline or new candidate due result has happened yet. Earlier
source-only statements above are historical progress and are superseded only
for deployment availability, not for the still-unfulfilled actual pipeline gate.

## Product reality and release preflight (new source, not activated yet)

`product.observed.python.v1` and `product.observed.frontend.v1` describe current
running component image IDs and their observation time. Revision labels remain
unattested claims in bounded text; source_commit/deployment_id/generation/owner
stay null. Independent frontend/backend revisions are legitimate. These version
events do not overwrite historical run provenance and do not prove a Pi release.
A confounded before/after census cannot be used as a coherent release base.

`product.release_preflight.v1` is a blocked plan listing missing evidence classes:
actual maintenance/provenance availability, functional pause/checkpoint/resume,
current source/ownership/epoch, compatible backup/restore, exact main adoption/CI,
explicit product release authorization and real business/owned rollback probes.
A table's presence is not a runtime acceptance receipt. Read/catalog failures
mean unknown, not absence. The observation/preflight data have no authority and
cannot be converted to approval by inserting approved/owner/attested fields.
The main reader still needs only auditv1; no new administrator auth or executor
capability is introduced.

The fixed observer has no provider route, opens no fee or manager ledger, imports
only stdlib/audit code, and has no Docker create/build/update or SQL write action.
It is a host capability with root-equivalent Docker-group trust; the six model
tools do not change. Separate source plan and qualification gate:
[product release preflight](../superpowers/plans/2026-10-29-pi-product-release-preflight.md).


## 产品只读探针实际启用更新（2026-10-29）

上述“新源码尚未启用”段落现由此事实更新：72ae3911/c4dfb595只读产品探针已通过两次普通隔离入口和两次systemd执行，15分钟定时器实际触发；原六角色均活动。main独立-I-S-B reader已验证实际组件版本、blocked发布前置计划、初次原生失败及导出批次阻断，原次日18/18关联仍保留。阶段源码13文件+738/-1属控制面，产品未发布。

有限付费控制器仍1ea1d514，当前参考profile17becf3b对齐实际222tracked后端文件d25d8275，context_budget字节不变；原Oct30 11:27+08到期和预算/预留不变。历史63383ce9是当时上下文，不应覆盖旧审计。新组件观测不升级为历史run源码身份、部署owner或发布审批。

证据与未完成门槛见[实际验收](../evaluations/pi-product-preflight-2026-10-29.md)及JSON。真实新候选、main/产品采用、业务版本回退与24–48h仍未验收；只读能力不得展示为完整自治管理者已上线。


## 源码集成审计交接更新（2026-10-29）

固定实现8179de5a及精确4项CI已通过；单次审查六项Important完成一次作者修复。后端2578/Pi离线3938/针对性119通过，未选入与既有预期失败单列。继承的产品功能保留，main/产品未采用；没有新增模型请求。完整范围与失败保留见docs/evaluations/pi-product-source-integration-2026-10-29.md及同名JSON/范围JSON。工具、记忆、设置、边界、回退审计及检查—开发—工具—次日—每日输出统一对照见docs/pi/management-audit-output-map.md。下一阶段是固定生产维护/兼容备份恢复操作包和隔离演练，不能以本次源码通过宣称线上管理者已完成。


## 产品来源存储探针更正（开发中）

实际来源由workflow记录在agent_runs.detail.run_provenance；任务元数据保存在tasks，payload为JSON。catalog v1的task_provenance/agent_run_provenance布尔名保留兼容，但新版实现仅表示tasks.payload/agent_runs.detail为JSON或JSONB存储，不能证明已有内容、完整来源或部署归属。旧实现查找不存在的独立run_provenance列，历史false观测与原收据保留。原始源码/配置身份、实际新运行来源与main采用仍需独立证据；探针不回填历史行，也不放行产品发布。修复已用独立真实PostgreSQL复现；源码尚待本维护计划最终审查与实际探针更新，不表示现有服务器探针已切换。

## Linux 引导与恢复阶段输出（2026-10-30）

源码b38d8a80的阶段输出见docs/evaluations/pi-native-bootstrap-checkpoint-2026-10-30.md/.json。独立标准库reader验证本地9事件、完整18路径、no_release以及blocked次日无结果；源实现、实际隔离服务、模型自主成果和生产采用分开统计。该导出未写服务器，当前管理员页面/权限也未变。本轮真实模型请求0；生产适配器在完整activate/rollback缺失时仍阻断，不能把局部恢复证明作为上线许可。

## 应用恢复与POST阶段（2026-10-30）

源码efd26876：4048项离线通过；显式真实服务验证为应用6项、PG/迁移6项、配对应用1项。冻结新旧镜像实际读取恢复数据，检查源码、HTTP启动、密钥/MFA、附件/TLS、所有租户（含空数据）、checkpoint/pending writes；POST绑定当前候选及持久身份，保留PRE之后新增数据。属于人工主机边界增强，不扩大Pi SDK六工具，不计为Pi自主开发绩效。新增9条本地审计，独立标准库reader验证本轮11路径与前轮9事件保留；未写服务器，次日blocked且无结果。生产activate/rollback仍未齐备，不称上线或业务回退。详见docs/evaluations/pi-application-recovery-2026-10-30.md/.json，仍按原累计50元及9笔未知预留边界推进。

## 原生容器生命周期交付（2026-10-30）

main只读接口无需新增执行权限即可读取本阶段9条投影、10路径范围和blocked次日计划；本地累计27事件，独立标准库reader已验。见[阶段JSON](../evaluations/pi-native-cohort-2026-10-30.json)。导出尚未追加服务器；三个阶段的次日计划均未注册、结果null。回退容器演练的PG归属切换使用测试固定SQL，不能展示成线上业务回退；完整产品发布、观察及回退仍需独立收据。

## 原生控制交付（2026-10-30）

本地只读导出累计36事件，其中[原生控制9事件](../evaluations/pi-native-control-2026-10-30.json)与8路径已由独立标准库reader验证。版本no_release，四阶段次日均blocked且result=null；仍未上服务器。native_candidate_open/native_legacy_return只对应合成服务接线，不能展示成线上业务部署/回退完成；当前生产ACTUAL能力门禁保留，最终业务/权限/长期观察须独立证据。
