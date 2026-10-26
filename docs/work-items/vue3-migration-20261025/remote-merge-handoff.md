# 远程交接与main合入准备（2026-10-26）

用户本轮授权整理提交并推送codex/vue3-migration，由main侧另行合并。本工作区不合入main、不发布、不创建PR、不删除分支。此前报告中的“未提交”是构建/验收时点事实；发布后的精确提交以Git历史和远程分支为准，不能把基线HEAD当作迁移成果。

## 身份与当前验证

- 仓库：https://github.com/frostloom/Myink
- 基线main：a96066c43b41e535da4b73e260a998ba9350c415；推送前远程main仍为该提交，迁移远程分支尚不存在。
- 源码与Vue/React构建字节摘要再次核对通过；推送前完整共享205、Vue576、React613测试通过，双端lint/types/build exit0；helper4、配置/资产Node5通过。日志push-verification。
- 最终浏览器三引擎12组与两个Caddy镜像回执仍对应当前源码/产物；本轮未重复浏览器、Docker和后端完整集成，不混称新跑。
- 最新技术报告safe-update-fixes.md、摘要build-provenance.json、回退preview-and-rollback.md。构建产物、node_modules、私有环境文件及捕获的公开旧assets不提交。代码所需retained-assets/.gitkeep会提交。
- 主工作区既有.DS_Store和docs/work-items未参与提交。Pi与admin独立开发分支未操作；这次仅迁移main基线上已有后台UI。

## main侧执行约束

1. 读取AGENTS.md、上述最新报告与方案，检查main工作区Git状态，保护已有未提交/未跟踪内容。
2. fetch origin，核实远程迁移分支提交，再审查origin/main与origin/codex/vue3-migration的真实差异。当前分支不是空的基线工作区；不要只按旧报告的HEAD判断。main有新增提交时评估冲突并保留双方有效逻辑。
3. 源码合入必须同时包含Python SSE终态修复及回归，不能只复制web；Pi不合入，不把独立admin分支合入。先本地合并并验证，不自动推送main或部署。
4. 安装锁定依赖后执行默认Vue及显式React的lint/test/build、helper和Node配置门禁；对后端SSE运行适当的隔离回归。按CI要求补足合并后检查，明确报告缺失/skip；固定myink-test资源不能并发或借用生产服务。
5. 确认默认dev/build/Docker/Compose是Vue，React只通过显式入口回退。不要删除React实现、测试或资源保留机制。
6. 发布是后续独立授权：先发安全React过渡版本、确认活跃用户保存/导出并重开，再切Vue。旧标签页不会自动获得保护。捕获当时运行旧镜像公开assets，携带Vue/React并集，配套已修SSE的API；不能直接把历史裸React镜像当安全回退，也不能因干净checkout缺少被Git忽略的assets而绕过准备。
7. 完成后报告合并提交、检查结果、残余P3和未执行事项；保留本迁移worktree/分支以便追溯。
