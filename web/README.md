# Myink 前端

前端只维护 Vue 3 + TypeScript，入口为 `vue/index.html` 与 `vue/src/main.ts`。`vite.config.ts` 和根 TypeScript 解决方案均指向 Vue。`src/lib`、`src/types.ts` 和 CSS 是共享服务、类型及样式，不是另一套应用。构建模块图禁止混入已退役框架运行时。

## 默认命令

需要 Node 24.22.x：

```sh
npm ci
npm run dev       # Vue :5174
npm run lint      # 共享 TS + Vue 模板/TS
npm test          # 共享 TS 测试 + Vue 交互测试
npm run build     # Vue 严格类型检查 + dist-vue
npm run preview   # 预览 Vue dist-vue
```

`dev:vue`、`build:vue`、`test:vue` 等保留为同一 Vue 应用的兼容入口。产物仅为 `dist-vue`。开发服务经 localhost:80 Caddy 代理 API；端口不同不代表后端数据隔离。

## 浏览器验收

```sh
npx playwright install --with-deps chromium firefox webkit
npm run build
npm run test:browser:matrix -- --output /tmp/myink-browser-matrix-unique
```

矩阵串行启动三个真实引擎，分别执行路由/认证/主题、工作台SSE/409及长文/下载/图片/视频/IME，以及两个真实 Vue 版本间的升级与回退安全回归；屏宽390、768、1440。输出包含每组receipt、日志和截图；未通过或无法启动任何引擎都令门禁失败。各引擎使用独占可清理的普通临时配置目录，不读取用户浏览器资料。WebKit隐私上下文本身不支持IndexedDB Blob持久化，不能拿隐私上下文冒充普通Safari持久化验收；实际手机硬件输入法仍与自动composition事件区分。

单组调试：

```sh
MYINK_TEST_BROWSER=webkit node scripts/vue-browser-smoke.mjs
MYINK_TEST_BROWSER=firefox node scripts/vue-readiness-browser.mjs --dist dist-vue --output /tmp/myink-firefox-unique
node ../scripts/evaluate-browser.cjs --dist dist-vue --output /tmp/myink-workspace-unique
```

以上是实际构建产物与loopback合成API/SSE，不能冒充真实后端/付费模型验收。此前真实隔离API→Rabbit→worker→本地模型HTTP及TLS证据单独保留。内存指标只在Chromium使用CDP采集；其他引擎未测该指标，记录为null。

## 镜像与旧资源

Caddy/Compose 仅接受 `FRONTEND_VARIANT=vue`。每次发布前运行 `scripts/prepare-frontend-assets.py` 捕获实际运行旧镜像公开资产，前端回退只能选择已验证的上一版 Vue。内容碰撞和符号链接门禁会拒绝不安全合并。

根目录 `python scripts/test_prepare_frontend_assets.py -v` 运行纯fakeDocker清理回归；`node --test scripts/merge-retained-assets.test.mjs scripts/default-frontend.test.mjs` 在web运行。API镜像门禁从根目录、同pytest Python环境运行：`python scripts/api-image-smoke.py --image <候选API镜像> --output <回执JSON>`。

前端配套后端须包含 SSE 终态尾帧修复；不改变浏览器存储格式。当前发布规则见 `../docs/DEPLOY.md`，迁移目录保留历史证据，不再作为当前回退指令。Pi 不在范围，提交/合并/上线仍按用户授权执行。

安全更新：构建生成与 HTML 内嵌身份配对的 `release.json`（无缓存），开发页不轮询生产版本。更新仅提示；用户确认前检查未保存输入，API 写入期间禁切换。Vue 内存表单离开保护见 `vue/src/composables/MEMORY_FORMS.md`。发布前仍需通知用户保存/导出，并准备旧 hashed assets；保留资源不提供旧应用的首页或选择入口。
