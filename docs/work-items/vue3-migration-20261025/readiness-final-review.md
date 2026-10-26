# 最终综合验收独立审查

2026-10-26，预审阶段。当前最终 DdkQzNNW 真实 TLS 浏览器及保留资产双镜像门禁仍执行中，本报告**不授予最终 readiness 通过**。只读审查，不运行 Docker、浏览器或重复全量测试，未修改产品、提交、推送、合并或部署。

## 当前结论

已关闭的两项业务竞态、两项 functional 原生事件问题、旧资产覆盖与 smoke 清理误报，在各限定独立复审内没有新的确认阻断。综合审查当前未发现新的可达产品缺陷；待执行门禁属于尚未完成的验证，不能换算成通过。最终可否技术放行须补审下表证据与清理结果。

## 行为矩阵与证据边界

| 要求 | 已有证据与判断 | 最终关闭条件 |
| --- | --- | --- |
| 认证/续期/改密/账号隔离 | session/auth/account 单测与独立105关联回归；真实安全10项有服务端撤权/MFA/owner附件权限。登录与续期语义保持分离 | 保留真实报告限制，不以合成登录证明后端撤权 |
| 长篇计划/流式/候选审核/修订/历史 | 真实 API→队列→worker→模型HTTP→DB/SSE13项及TLS3项；Plan原生change崩溃已有实际RED与独立11项GREEN | Ddk真实browser必须保留编辑Plan、确认POST、持久化approved_plan和worker完成断言 |
| 短篇资源优先/显式生成/恢复 | API真实短链与Workspace/Create单测；资源选择不应隐式入队 | Ddk真实browser resource-first、manual-start及reload恢复结果 |
| 大正文/IME/409/滚动/媒体/移动反馈 | 同harness Vue A→React→Vue B各24项，真实DOM/媒体但API为fixture；报告精确绑定Cyxw | 不把Cyxw A/B提升为Ddk全量浏览器证据；Ddk仅两字段修复的影响由限定回归+真实链路说明 |
| 路由/admin/资源版本 | 原72文件登记与Vue映射，router parity；admin单测及真实MFA/资源409/反馈字节门禁 | 路由登记不替代行为；保留单测/合成/实际API的分别归属 |
| 同源Vue↔React恢复 | preliminary已证明active task、draft/theme/session恢复，失败旧receipt未计通过 | 最终Ddk完整browser receipt成功、资产身份一致、不重复generate |
| 旧客户端与回滚 | 内容安全merge、immutable捕获、3独立Node tests，默认React selector与保留Vue资产的React回退准备 | 最终两镜像ID/labels/index、运行时/深链/cache/旧hash取回及cleanup证据 |
| 全量基础门禁 | 报告Vue561/React599、type/lint/build、audit0；Python1949+1skip+5xfail已明确解释 | skip/xfail保持非通过；不宣称运行了固定myink-test总脚本或无gateway的Go检查 |

## 源码/配置核对

- 冻结身份以 `build-provenance.json` 的 Ddk JS SHA 与 index/CSS摘要为准；未提交HEAD只代表基线。Cyxw、BDxd和线上历史Cvlt均已区分。
- router实际涵盖现有产品与admin路由；候选生产边界禁止React/旧TSX。复用API/存储协议，版本提示不自动刷新，仍需用户保存后刷新。
- Caddy保持SSE独立匹配与flush_interval -1，API未知版本JSON404；hash immutable、HTML no-store。构建selector默认React、非法值失败，两变体统一运行路径，不改变数据库/schema。
- 当前merge预扫描阻断同名异内容后才追加旧hash；Docker运行层单次复制统一输出。捕获使用immutable image ID，无启动生产容器或数据挂载需求。
- CI实际包含React/Vue检查、合成浏览器和双镜像build；合并测试纳入门禁。ci-local最后明确仅基础门禁、浏览器/Vue镜像另验，未把缺失步骤宣传为完整替换验收。
- smoke对browser/container/network逐项清理，清理失败令receipt失败；实际资源清理仍须由本轮执行证据确认。

## 待统一的报告状态

`replacement-readiness.md` 已明确最终pending；但active plan仍全为未勾选，`readiness-real-chain.md` 仍保留最终pending及Cyxw blocker章节，`readiness-packaging.md` 仍保留完整Vue待串行复跑文字。它们是历史执行状态，不能据此独立推导最终结果。收到最终回执后，应保留失败历史同时追加明确superseded说明、更新最终状态及计划完成项；不能仅更新总测试数量。

生产DNS/公网证书、真实手机IME、长期旧客户端窗口及付费模型质量边界已明确，没有伪装为已执行。本次无额外测试结果；此前限定独立运行证据位于readiness-defect-review及readiness-packaging-review。等待最终browser/双镜像/cleanup回执补审。

## 追加：Rail 双 logout P2 独立复审

开发完成删除冗余 emit 后，独立读取 ProjectRail、AdminRail、ProjectRail.test、App 与实际父组件调用，并搜索其余 defineEmits/emit 路径。限定结论：双 logout P2 修复正确，当前未发现新的同源事件重入问题。

两 Rail 的 `onLogout` 由 defineProps 声明，模板 `@logout` 编译后同样是该 prop listener；现在 leave 仅在显式 handler 与 auth fallback 二者中选一个并 await，不再先 emit 再直接调用。ProjectRail 的 render-function `onLogout`、AdminPage 的 `:on-logout`、无传参 fallback 都保留。App 的 route listener 不构成额外 emit 路径。ProjectsPage 只 emit logout、未再调用同名业务prop；ChapterEditor、VersionHistory、ConnectionNotices 的相应事件也没有 emit 与同名显式prop双调用结构。

实际轻量运行（web）`npm run test:vue -- vue/src/components/ProjectRail.test.ts`：1文件、7 tests passed、0 skip、exit0。包含两个 Rail 显式handler均恰好一次且不调用fallback、ProjectRail fallback一次，以及Admin fallback现有用例。未重复开发者的4文件49项、type/lint/fullVue，也未运行浏览器。开发者原2RED为其实际证据，本角色仅独立验证GREEN与代码语义。

Ddk原有真实链路通过不覆盖本次新增产品修改；必须以修复后新资产身份重建并验证Workspace显式handler退出仅一次请求，以及原完整链路。最终保留双镜像与运行资源清理仍待完成，当前继续不作最终放行。

## 追加：SSE observer 尾帧阻断独立复审

已读取 `routes_sse.py` 完整路由、diff、`test_sse.py` 新17项边界、历史恢复用例、conftest及实际observer生产逻辑。限定结论：此次真实SSE阻断修复正确，未发现新确认安全/隔离退化或恢复语义问题。

历史终态只有在后续authoritative `event=status`出现时才被替代；observer实际只写node且不写status，因此metrics/summarize尾帧不能使done/failed/awaiting_plan/awaiting_review/cancelled失效。已读Last-Event-ID后的范围仍用XRANGE严格排除起点；若该范围没有状态，则反向查找游标以内最新状态，只判定是否关闭、不重发旧ID。若最新状态为queued/running，仍进入live读取；已有终态且只剩尾node时发新node（如有）后结束。查询使用同一已授权task key，route的JWT验证、task ownership预检、410、deadline、live heartbeat复检均未改；无新外部参数/越权路径。

新增XREVRANGE仅在后游标范围没有status时执行，当前Redis流由生产点MAXLEN约1000约束；可能读到整个保留窗口，不等同新增无限历史查询。XRANGE与XREVRANGE之间的追加事件仍由原last游标进入live读取，不会因本次辅助查询主动越过新ID。此结论不替代真实Redis端到端复验。

实际独立运行临时Python3.12环境，仅 `test_sse.py` 的四组新replay回归：**17 passed、33 deselected、0 skipped、exit0**，0.86s。唯一warning为既有Starlette/AnyIO BlockingPortal弃用。运行前确认这些用例以_ReplayRedis monkeypatch get_redis、无DB fixture，autouse仅patch配置；未触达真实DB/Redis/队列，未运行整库或浏览器。命令为：

```sh
APP_ENV=test EMBED_ENABLED=0 JWT_SECRET=test-jwt-secret-at-least-32-bytes-long /tmp/myink-vue-real-venv-2305/bin/python -m pytest tests/test_sse.py -q -k 'replay_delivers_terminal_before_late_observer_node or replay_skips_waiting_terminal_only_when_status_resumes or replay_cursor_after_terminal_does_not_wait_on_observer_tail or replay_cursor_after_resume_does_not_treat_old_wait_as_current'
```

新后端改变必须进入最终真实11项浏览器/edge以及隔离全量Python回归的身份范围；旧Ddk成功不覆盖此变更。最终LHE host27/10/24由主代理已报告GREEN，仍待最终backend/镜像/cleanup证据汇总补审，当前不作最终放行。

## 最终回执补审（镜像门禁尚未齐备）

独立读取durable `readiness-final-real-chain-browser-receipt.json`、edge receipt、cleanup JSON、full Python日志及更新的real-chain报告。browser确为LHE入口、11 checks、passed=true、pageErrors=[]，httpFailures仅预期404/410、无5xx；HTML SHA明确与JS SHA分开。edge四项包含新worker增量TLS与原真实done→summarize流的同输入修复验证，终态后游标只发新node并EOF，不重发旧ID。cleanup记录5容器（含原zombie）、专用network移除exit0，8端口无监听、无剩余专用容器，保留既有栈。上述均为独立读回执，不冒称本角色执行了真实链路或清理。

同时独立计算当前dist-vue四文件SHA，均与build-provenance一致；LHE JS为 `8ace8616b0dc484c661be17834853f6a81fc1c95f4179f185173f46a2f12f51a`，当前routes_sse SHA与provenance的 `39587e77c3cb7334519f1e0957c2ba3d680e93f3336164ea62167a3afccb1454` 一致。spec当前有113路径，字节未变由主代理契约导出对比证明，本角色未重新导出。

full日志尾部实际1966 passed、1 skipped、5 xfailed、2 subtests，环境污染失败历史与最终清洁env运行已区分。唯一skip是SDK评测的固定15432安全身份边界，5xfail为基线语义检测缺失，均仍非通过；不属于本次SSE/前端替换被静默移除的失败。API13/security10属于较早运行，报告已明确未在最终后端完整重复23场景；新增后端由final Python、新handler edge4与LHE browser11覆盖。

`preview-and-rollback.md` 已明确本轮包含共享SSE API补丁：上线必须使用含修复的API，不能仅切Vue静态入口；React回退继续使用修复后API，因无schema/存储格式变化，无需回退该修复或清作品数据。这是本轮部署依赖，不是新的授权。本轮仍未部署。

已获主代理Vue canonical镜像构建+7smoke通过消息，React回退镜像与API补丁镜像仍在准备；等待durable image receipts后再作最终身份/旧hash/cleanup核对。当前未发现新增确认产品阻断，但不提前宣告镜像相关项全部完成。总报告、provenance状态与packaging历史pending文字仍需最终同步。

## 最终独立签核（替代以上历史 pending 结论）

2026-10-26，最终只读补审完成。**本候选具备按本轮明确验收矩阵替换 React 的技术条件；无开放确认缺陷或关键验证遗漏阻断。** 该判断针对未提交候选及已记录不可变镜像，不是生产发布授权，也不是对全部未知缺陷的保证。

已独立核对三份durable镜像回执：Vue `3eb69714f94c5065e26a16f95a4fba66ec7718ca2d73b5cd9c297c2f3d3ba674`、React `32513ef95870cb847d796c5bf4fe6d021194a4afc15b69007301633f5a6d7335`、API `9b5fb658fd5b6c5fb4c36e7ed74e207bcd6d48364c29a23be1bfbc863cd32b9b` 与provenance一致。两前端分别7 checks passed、pageErrors=[]、cleanupErrors=[]；入口分别LHE/BDxd，保留资产回执8文件含原Cvlt与最终LHE，并记录双镜像同集同SHA。非法selector构建日志明确内部exit64，cleanup回执确认无错误标签、无自有容器/network残留。

API回执passed=true、cleanupErrors=[]，SSE源码SHA与本次独立验证过的源码一致，25核心依赖版本、113路径合同和healthz200通过。其实际DB/队列/worker能力由前述final实链与full1966提供，未把无网络TestClient boot误作全服务集成。已审查新增api-image-smoke的创建前cleanup责任登记：CLI部分失败后仍在finally尝试rm，失败保持非0/false；不吞清理错误。主代理的纯fakeDocker故障注入与真实positive重跑证据作为其执行结果，不称为本角色重复执行。

最终replacement-readiness、packaging、runbook、coverage、provenance与active plan已消除先前状态不一致：中间Cyxw/Ddk、env污染和Docker取消/僵尸失败保留历史，最终LHE+修复后SSE+canonical三镜像有独立身份与通过回执。之前本报告的“待镜像/待最终链路/暂不放行”均为当时阶段状态，由本节最终结论替代。

1个Python skip与5个baseline xfail继续明确不算passed；其理由与本次验收范围已审核。未执行的公网DNS/证书签发、真实手机硬件IME、长期在线窗口、付费模型创作质量均保留边界，没有用单测数量或本地TLS冒充。实际发布仍需用户明确授权，固定授权提交/镜像身份并重新读取部署当时的旧资产窗口；含修复的API是部署依赖，React回退可保留它，无需schema或草稿清理。

本角色未启动Docker/浏览器、未重跑大测试、未修改产品。本次最终结论基于独立源码/配置审查、此前亲自运行的105关联/11字段/7rail/17纯SSE/3merge限定验证，以及逐项读取最终durable链路、构建、镜像、负向与清理证据。签核完成后停止写入。
