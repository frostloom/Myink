# 替换准备构建与依赖独立审查

审查时间：2026-10-26。范围为 Task 4 的 Caddy Dockerfile、Compose caddy build args、Docker context、CI、package/lock 及 frontend-image-smoke；未重复业务代码审查，未启动服务或执行 Docker 构建。

## Spec 结论

构建选择设计符合要求：全局 FRONTEND_VARIANT 默认 react，两阶段各自重新声明 ARG；case 仅接受 react/vue，非法值退出 64。npm ci 层不依赖变体，构建层依赖 ARG，缓存可以共享依赖但不会复用错误变体。仅把所选 dist/dist-vue 复制到 /app/frontend-dist，再进入运行镜像；.dockerignore 排除两套宿主输出。Compose 默认 React，Vue 明确 opt-in；运行层带 io.myink.frontend。Node 构建/CI 均为 24.22.1，engines >=24.22.0 <25 与本机 24.22.0 相容。

CI 两套检查、构建与浏览器命令执行顺序合理，--dist 从 web cwd 解析到正确目录。Vue 配置有打包模块边界门禁，未发现混入 React 的路径。package-lock 根依赖/devDependencies/engines 与 package.json 一致，npm ls --depth=0 正常；Vite 8.2.4、Vitest 4.1.12 实际安装版本一致。

尚不能独立宣告最终 readiness：双镜像、非法参数构建和实际镜像 smoke 由主代理验证；本审查不把正在执行的验证视作通过。

## Quality finding

**[P2] image smoke 的清理失败仍可报告通过，且浏览器关闭失败会跳过剩余清理与回执** — `web/scripts/frontend-image-smoke.mjs:59-63`。

receipt.passed 在清理前设置为 true；docker rm/network rm 的失败被空 catch 吞掉，脚本仍退出成功并输出 passed:true。若 browser.close 拒绝，后面的 Docker 清理和 receipt 写盘都不会执行。其实际影响是验收报告无法证明计划要求的临时资源清理，异常时可能残留运行容器/网络，也可能丢失原始失败证据。应分别尝试各项清理，记录失败并让最终门禁失败，同时保证 receipt 无论浏览器关闭结果如何均写盘。此问题不影响已构建产品行为，但影响验收 harness 可靠性；修复后可轻量故障注入验证 cleanup 失败不可报绿。

## 实际检查及限制

- 已执行 `node --check web/scripts/frontend-image-smoke.mjs`，通过。
- 已用 Node 比较 package.json 与 package-lock 根字段，通过；`npm ls --depth=0` 通过。
- 本地 Node v24.22.0。
- 独立 `npm audit --audit-level=moderate --json` 失败：sandbox DNS `ENOTFOUND registry.npmjs.org`；不能作为 audit 0 的独立复核。
- Python YAML 解析因缺少 PyYAML 未执行成功；本机 web node_modules 也无 yaml/js-yaml。CI YAML 已人工核对缩进、working-directory 和步骤依赖，未把人工核对表述为解析通过。
- 未运行共享服务，未执行生产切换、提交、推送或部署。

## 复审：清理修复与旧公共资产保留

已重新读取 smoke：逐项独立捕获 browser/container/network 清理异常，cleanupErrors 非空会 passed=false 且 exitCode=1；原清理 P2 关闭。根代理的真实 Docker 故障注入回执属于根代理验证，本复审没有重复启动 Docker。

新 helper 已独立运行 `/tmp/myink-review-retain-test.py`，使用临时目录复制 helper、fake Docker，不改项目资产、不访问 daemon：首次导入、重复导入、内容碰撞拒绝、保留原文、拒绝符号链接、清理失败非0、5条路径全部执行 rm -f -v，7项断言通过。helper 仅 create 停止容器并使用 network none；移除带 -v；目标路径检查防止经目录链接写出 retained-assets；.gitignore 保留目录锚点并忽略导入文件。

**新 [P2] retained-assets COPY 可静默覆盖当前构建的新文件** — `caddy/Dockerfile:36-38`。helper 只校验此前保留的文件彼此同名同内容，没有比较它们与这次构建的 assets。Docker COPY 在新产物之后合并旧文件，同路径内容不同会直接覆盖，导致 index 引用的当前 JS/CSS 被替换。即使正常 Vite 哈希令碰撞罕见，手工公共资产或旧镜像异常同名仍会绕过已有“从不静默覆盖”保证。应在构建时将两套目录逐文件校验，冲突直接失败，合并后再复制最终目录。本项仅静态确认 Docker COPY 语义，未构建新镜像。

另建议 helper 的 `docker create` 使用前一步 inspect 得到的 immutable identity（当前 scripts/prepare-frontend-assets.py:32/37）；目前回执记录 id 而 create 使用可变 tag，tag 并发变更会使回执与实际源不一致。尚未实际发生，不把它描述为已观察到的产物错误。

真实保留资产镜像构建尚待根代理完成；本次不报告替换准备全部完成。

## 再复审：保留资产与当前产物的内容安全合并

2026-10-26，独立只读复审当前 `caddy/Dockerfile`、`scripts/prepare-frontend-assets.py`、`web/scripts/merge-retained-assets.mjs` 及其测试。未运行 Docker、浏览器或大测试，未修改产品/构建脚本。

原“retained-assets COPY 可静默覆盖当前构建新文件”P2 已关闭：Dockerfile 在 web stage 先产出所选前端，再把旧资产放入独立 `/app/retained-assets`，调用合并脚本校验，最终运行层仅从 `/app/frontend-dist` COPY 一次。脚本对所有源文件预扫描：拒绝源符号链接/特殊文件；同路径目标必须是普通文件且逐字节相同，否则在复制 pending 文件前失败；目标不存在才加入复制队列。因此旧不同内容文件不会覆盖本次 index 所引用的新代码。同内容复用与缺失旧 hash 追加两条正常路径保持有效。`prepare-frontend-assets.py` 的 create 现使用 inspect 返回的 immutable identity，回执 ID 与实际捕获源一致，先前 tag 竞态建议已落实。

实际独立运行 `node --test web/scripts/merge-retained-assets.test.mjs`：3 tests passed、0 failed、0 skipped、exit 0。覆盖正常合并且保留新产物、同名异内容拒绝且新内容不变、源 symlink 拒绝。此前 cpSync 模拟旧行为的 RED 为主代理证据，本次未重复执行或将其标为自己的运行。

限定配置与合并逻辑复审未发现新确认缺陷。这里的通过不替代最终镜像构建、镜像资产身份检查和真实旧客户端访问验证；这些由主流程验收。本角色追加后停止写入。
