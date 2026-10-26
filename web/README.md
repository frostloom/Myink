# Myink 前端

迁移分支默认开发、构建与检查现已使用 Vue 3 + TypeScript，入口为 `vue/index.html` 与 `vue/src/main.ts`。`vite.config.ts` 指向 Vue 配置，根 TypeScript 解决方案也指向 Vue。运行中的 main/线上服务尚未切换，本轮没有提交、合并或发布。

React 19 代码保留在 `src/`，只通过明确的 `*:react` 命令构建、验证与回退。共享的 `src/lib`、`src/types.ts` 和 CSS 仍单源复用。Vue 产物的实际模块图禁止加载 React 运行时和旧 TSX。

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

`dev:vue`、`build:vue`、`test:vue` 等保留为兼容入口。Vue 输出 `dist-vue`，React 输出 `dist`，避免新旧产物相互覆盖；目录名不代表默认框架。两个开发入口均经 localhost:80 Caddy 代理API；端口不同不代表后端数据隔离。

## React 回退验证

```sh
npm run dev:react       # React :5173
npm run lint:react
npm run test:react      # 完整既有 React/共享测试
npm run build:react    # React -> dist
npm run preview:react
```

观察和回退窗口结束后的删除旧实现是独立事项。本轮不删除旧测试，也不把同一共享测试在默认与回退两次运行当成不同覆盖。

## 浏览器验收

```sh
npx playwright install --with-deps chromium firefox webkit
npm run build
npm run build:react     # 更新安全检查会在两套实际产物间切换
npm run test:browser:matrix -- --output /tmp/myink-browser-matrix-unique
```

矩阵串行启动三个真实引擎，分别执行路由/认证/主题、工作台SSE/409及长文/下载/图片/视频/IME，以及双框架真实版本切换安全回归；屏宽390、768、1440。输出包含每组receipt、日志和截图；未通过或无法启动任何引擎都令门禁失败。各引擎使用独占可清理的普通临时配置目录，不读取用户浏览器资料。WebKit隐私上下文本身不支持IndexedDB Blob持久化，不能拿隐私上下文冒充普通Safari持久化验收；实际手机硬件输入法仍与自动composition事件区分。

单组调试：

```sh
MYINK_TEST_BROWSER=webkit node scripts/vue-browser-smoke.mjs
MYINK_TEST_BROWSER=firefox node scripts/vue-readiness-browser.mjs --dist dist-vue --output /tmp/myink-firefox-unique
node ../scripts/evaluate-browser.cjs --dist dist --output /tmp/myink-react-unique
```

以上是实际构建产物与loopback合成API/SSE，不能冒充真实后端/付费模型验收。此前真实隔离API→Rabbit→worker→本地模型HTTP及TLS证据单独保留。内存指标只在Chromium使用CDP采集；其他引擎未测该指标，记录为null。

## 镜像与旧资源

Caddy/Compose默认 `FRONTEND_VARIANT=vue`；React回退必须显式选 `react`。每次发布前运行 `scripts/prepare-frontend-assets.py` 捕获实际运行旧镜像公开资产，回退镜像还需保留Vue资产。内容碰撞和符号链接门禁会拒绝不安全合并。

根目录 `python scripts/test_prepare_frontend_assets.py -v` 运行纯fakeDocker清理回归；`node --test scripts/merge-retained-assets.test.mjs scripts/default-frontend.test.mjs` 在web运行。API镜像门禁从根目录、同pytest Python环境运行：`python scripts/api-image-smoke.py --image <候选API镜像> --output <回执JSON>`。

本轮SSE终态尾帧修复需随前端切换使用，React回退仍可使用该修复API；无schema或浏览器存储格式迁移。报告、学习顺序与回退操作见 `../docs/work-items/vue3-migration-20261025/`。Pi不在范围，提交/合并/上线仍按用户授权执行。

安全更新：两个框架的构建都生成与HTML内嵌身份配对的`release.json`（无缓存），开发页不轮询生产版本。更新仅提示；用户确认前检查所有未保存输入，API写入期间禁切换。Vue内存表单离开保护见`vue/src/composables/MEMORY_FORMS.md`。已打开的更旧React不会自动获得保护：实际发布需先发安全React过渡版本，通知用户保存/导出并重开，最后再按授权切Vue。
