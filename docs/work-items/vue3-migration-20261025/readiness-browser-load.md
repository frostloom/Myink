# 浏览器交互与长内容验收

2026-10-26。独立测试范围：保留的 React 与 Vue 真构建在 Chromium 中运行；API/SSE 为白名单 loopback fixture。不会调用实际后端、数据库、队列或模型，不能代替另行 full-chain 验收。没有修改产品源码、提交或部署。

## 可复跑入口

```bash
PLAYWRIGHT_BROWSERS_PATH=/tmp/myink-vue3-browsers node web/scripts/vue-readiness-browser.mjs --output /tmp/myink-readiness-UNIQUE-vue
PLAYWRIGHT_BROWSERS_PATH=/tmp/myink-vue3-browsers node web/scripts/vue-readiness-browser.mjs --dist web/dist --output /tmp/myink-readiness-UNIQUE-react
```

输出目录须不存在。目录内包括冻结构建快照、真实截图、receipt.json、失败时的 DOM 文本与截图。回执记录构建 index 内容、所有静态资产 SHA-256、harness SHA-256 和实际 API 请求，未知 endpoint/method、非已知 task SSE 或外部请求立即拒绝并在最终断言失败。浏览器、loopback server、SSE 连接在 finally 清理。每次独立浏览器 context，不接触现有用户浏览器资料。

## 已实测范围与门槛

- 同一 fixture：400 章列表，20,000 与 50,000 Unicode code points（含 emoji/非 BMP 汉字）的已保存正文，完整内容核对、20 次真实按键、成功保存。输入耗时包括两次 Playwright 按键与两帧 RAF，因此是保守交互 roundtrip，不能当纯 DOM handler 时间。
- 250 个含非 BMP 字符的密集 SSE delta，合计51,672 Unicode points；完整文本比较、用户向上滚动后停止跟随、返回最新、断线期间新增 Unicode 补帧，带 cursor 重连后实际 replay 补帧且正文不重复。
- 手动 Plan 确认、刷新恢复人工候选拒绝并 resume；保存409保留本地正文、展示服务器正文、阻止无意覆盖。
- 真实 PNG 上传→IndexedDB blob→刷新；Chromium canvas/MediaRecorder 当场编码 WebM→真实上传→IndexedDB→刷新解码播放；动态 reduced-motion 停止/恢复，切换图片后 video DOM 移除且已用 object URL 被 revoke。
- 反馈文字与真实文件在关闭重开、SPA 离页后保留；Tab/Shift+Tab 焦点循环、Escape 关闭；390px 无 body 横向溢出，390×500短视口中聚焦描述可滚动进入可视区域。
- Chromium dispatch 的 compositionstart/keydown Enter(isComposing)/compositionend 实测不误提交反馈或保存章节。这是 composition event 路径，**没有验证真实手机键盘、OS IME 候选窗或软键盘**；短视口是 resize 模拟。

预先采用宽松且可诊断的可用性上限：输入 p95 < 1500ms；50k SSE 突发完整渲染 < 5000ms。p50/p95 和 GC 后 heap 必须同时记录并与同 harness 的 React 比较；机器短时变慢不直接判作产品缺陷。此上限用于阻止可重复的秒级卡顿，并非承诺每次输入在 16ms 内完成。只有持续重现且明显偏离 React 的退化才需要进一步定位。GC heap 是页面 JS live heap，不含浏览器进程、媒体解码器与 GPU 总内存。

## coverage 审计

原72份测试文件登记已逐行检查：单源 lib/protocol 继续由原测试验证；Vue 映射覆盖 renderer/lifecycle，不能把映射表本身当浏览器证据。已有 `vue-browser-smoke.mjs` 实际覆盖游客无保护API、登录失败/成功、短篇/创建/刷新、主题、账号/环境草稿续期、删除取消/409、注册邀请、MFA失败/成功、admin刷新等；原 `evaluate-browser.cjs` 覆盖工作台 Plan/SSE/409。

本文件新增浏览器证据集中补上原映射中的 ChapterEditor/StreamingChapterView、useTaskEvents、Appearance/CanvasMedia/themeImage、FeedbackWidget、ProjectRail/移动布局的真实 DOM、媒体、IndexedDB 和键盘边界。其余资源设置/409、管理员CRUD、MFA服务端撤权、完整长短任务和旧客户端缓存/回滚由对应集成任务验证；不能由本脚本的页面标题或合成返回值补算。所有路由注册依然由 router parity 与既有模块单测负责，完整真实服务行为需引用 full-chain 报告。

## 最终稳定构建验收

根代理暂停编译、单测及其他浏览器后，按 Vue A → React → Vue B 串行执行同一脚本，每次全新 Chromium。三次均 exit0、passed=true、24 checks、page_errors=[]、unknown_routes=[]。固定上限保持原值，未放宽断言或超时。

| 构建/轮次 | Unicode points | 输入 p50 ms | 输入 p95 ms | GC live JS heap bytes | 页面载入+20次交互+保存 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Vue A | 20,000 | 50.9 | 67.2 | 8,813,356 | 1807.8 |
| Vue A | 50,000 | 65.1 | 114.4 | 8,968,084 | 2064.1 |
| React | 20,000 | 49.9 | 68.4 | 8,523,404 | 1721.6 |
| React | 50,000 | 61.6 | 106.9 | 8,878,152 | 2294.1 |
| Vue B | 20,000 | 61.6 | 81.5 | 8,815,856 | 2174.9 |
| Vue B | 50,000 | 132.5 | 248.8 | 8,966,856 | 5952.8 |

同一51,672点/250帧 SSE 突发完整 DOM 渲染：Vue A 202.0ms、React 213.6ms、Vue B 758.0ms。输入 p95 均低于1500ms，SSE均低于5000ms。Vue B 的50k较慢，报告保留实际值；没有重复秒级输入卡顿或持续失去跟随/文本错误。此次样本不足以承诺Vue比React更快，或将轮次差异归因于框架。历史重CPU并发期间同机React p95也曾达694ms，停止并发后的同脚本React降到107ms；因此不把单轮machine slowdown当产品缺陷。

回执与冻结静态资产：

- `/tmp/myink-readiness-final-vue-a/receipt.json`
- `/tmp/myink-readiness-final-react/receipt.json`
- `/tmp/myink-readiness-final-vue-b/receipt.json`

三个回执 harness SHA-256 均为 `6379788183b67c20856f5683677a4abaf5356466b4c0f5936af77be9c1f15f4b`。Vue `assets/index-CyxwGv2c.js` SHA-256 `9dcb68bd386d5110eae6b9574d9f1e19560230f8f21bd1bbd71397135e18ec7c`；React `assets/index-BDxdzfd9.js` SHA-256 `957a9753c89e8df23790c702aeae91a023eeb0ac2505eb3f1448440ee99190c7`。全部被测内容复制到各输出目录 `built-assets/`，后续重新构建不会改变本次证据。每次fixture另有unknown endpoint/wrong HTTP method返回500的自检，不能靠空泛返回200掩盖漏接API。

Vue B 与 React 的 `05-mobile-feedback-focused.png` 已实际查看：390×500下描述输入可见，文件与后续操作可在对话框内滚动；键盘Tab环、Escape、文件跨路由保留由浏览器断言验证。

中间失败均为测试 fixture/同步错误：切换20k→50k时有意备份草稿保留、400章全部声明planning使恢复目标为400、异步IndexedDB写入尚未完成即刷新、移动端使用了不显示的灯泡入口。已修正fixture、等待持久化和使用实际移动导航；未将这些当作产品bug。原失败receipt与截图仍保存在01–04临时目录，没有删除或伪报为通过。

本验收范围无开放确认缺陷。浏览器任务完成，产品候选最终ready仍需合并另行真实API/worker/TLS/回滚和独立审查结论。没有提交、推送、发布或生产切换；finally已关闭自建Chromium、SSE和loopback server，保留回执/截图/冻结资产供审查。

## 最终Ddk修复版本补验

两处原生change/blur修复后，root对冻结index-DdkQzNNW.js补跑完整同一24项harness：/tmp/myink-vue-final-ddk-readiness/receipt.json，passed=true/exit0，unknown_routes与page_errors均空。另标准browser27项exit0（myink-vue-browser-IoIlDp）、workspace10项passed=true（/tmp/myink-vue-final-ddk-workspace/receipt.json）。该补验不调用真实API/模型，不能替代real-chain门禁。

最终Ddk 20000 Unicode points，400章节：input p95 85.8ms，live heap 8815784 bytes，载入/交互/保存 1942.3ms。

最终Ddk 50000 Unicode points，400章节：input p95 66.4ms，live heap 8958364 bytes，载入/交互/保存 1756.6ms。

51672点/250帧渲染 294.5ms，全部原断言保留。三轮旧A/B数据仍绑定Cyxw，未改写其身份。root实际查看最终390×500反馈聚焦截图，描述框完整可见，附件/操作区域由弹窗内部滚动访问。最终脚本finally关闭自有Chromium/streams/loopback server。

## 双登出修复后LHE最终补验

index-LHE4QUm9.js（仅两rail删除重复logout分发）完整Vue76/564及type/build通过后，root串行重跑标准27、workspace10、同一readiness24，全exit0。回执：标准日志/tmp/myink-vue-lhe-standard.log，workspace /tmp/myink-vue-lhe-workspace/receipt.json，readiness /tmp/myink-vue-lhe-readiness/receipt.json；两JSON passed=true，无未知API与页面错误。Ddk前序结果保持历史身份；最终release以LHE身份为准。真实new-backend+LHE11项、edge和镜像另验，不能由本节推断。
