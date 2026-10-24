# 可配置写作资源 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 不自动提交推送，不运行收费模型请求。

**Goal:** 后台发布真实写作资源，用户为作品选用快照、选择是否更新，后台可回退，个人自定义始终独立。
**Architecture:** 平台资源和不可变修订、发布事件、作品资源选择快照与个人资源分开持久化。生成入口统一解析已选快照，保留现有私有上下文和格式协议。
**Tech Stack:** SQLAlchemy/Pydantic/FastAPI、React/TypeScript/CSS Modules、pytest/Vitest。
**Spec:** docs/superpowers/specs/2026-10-24-writing-resources-design.md

## Global Constraints
- 仅在 codex/admin-control-plane 现有 worktree 工作，保护已存在的管理员 UI 未提交改动。
- 真实来源初始化，不杜撰文本；main 的 prose_rules.py 定向移植，不整体合并 main。
- 用户内容不写入平台资源库；平台管理接口不返回个人样本或私有资源正文。
- 作品保留快照，用户主动更新；当前运行任务不受平台发布回退影响。
- 输出协议、权限校验与工具约束不进入可关闭资源。

## Review Focus
- 发布与回退并发：expected generation 不匹配返回409，不丢历史。
- 更新提醒按发布事件去重，关闭不改资源选择，回退也能识别。
- 有用户修改的副本不被平台更新覆盖，跨用户和跨作品请求失败关闭。
- 当前任务资源固定，后续用户更新不修改已受理请求及原账本。
- 第三方参考资料保持来源许可、按需读取及字符上限，未选资料不被工具读取。

### Task 1: 资源、版本与发布状态
Files: 新增 src/myink/models/writing_resource.py、src/myink/writing_resources.py、tests/test_writing_resources.py；修改 models/__init__.py、db.py 的初始化与RLS入口。
Interfaces: 平台资源类型 reference/genre/genre_rule/style/writing_rule/expression_rule；不可变修订 body/source，平台资源 current_revision、generation；发布事件 publish/rollback；个人资源单独表以user_id归属；作品选择有resource_id、revision_id、body快照、personal_override、dismissed_release_id。
- [ ] RED：SQLite单元测试发布不可覆盖历史、回退指针不删新版本、并发409、个人保存不产生平台资源。
- [ ] 实现版本服务与幂等建表；项目/个人表接入适用权限和RLS。
- [ ] GREEN：单元测试；隔离PostgreSQL迁移与隔离测试，不使用实际用户数据库跑测试。

### Task 2: 真实来源初始化与管理API
Files: 新增 writing_resource_seed.py、api/routes_writing_resources.py、tests/test_writing_resource_routes.py；修改 api/main.py 装配；沿用 prompt_catalog.py、genre_catalog.py、reference_corpus.py。
Interfaces: /api/v1/admin/writing-resources 列表/草稿写入，/{id}/revisions、/{id}/publish、/{id}/rollback；写入携带 expected_generation。用户 GET /api/v1/writing-resources 仅列当前已发布资源。权限与审计沿用 require_admin/_audit_or_fail/no-store。
- [ ] RED：导入真实37题材、6精调、4内置文风、真实参考资料与创作/表达规则；重跑初始化不覆盖管理员编辑。
- [ ] RED：普通用户不能管理、目录不泄漏草稿和个人资源、回退保留历史、失败审计不继续写。
- [ ] 实现只导入已有固定内容；从模板中划分可配置创作偏好与固定协议，记录对应实际作用环节。
- [ ] GREEN：相关服务、API与契约测试；导出 spec/api-openapi.json。

### Task 3: 用户私有资源与作品选择API
Files: 新增 api/routes_user_writing_resources.py、writing_resource_selections.py、tests/test_writing_resource_selections.py；项目设置与创建入口增加选择兼容逻辑。
Interfaces: /api/v1/my-writing-resources 维护自己的资源，/api/v1/projects/{id}/writing-resources 读取/设置作品选择；/updates 获取差异与目标发布事件，/dismiss 只标记提醒已读，/adopt 原子接受勾选资源并生成新快照。
- [ ] RED：个人A/B隔离、无权作品不可读写、自定义不反向写平台；用户选择只接受已发布且类型/作用环节合法资源。
- [ ] RED：平台发布不改作品；主动采用更新才变快照；拒绝/关闭不更新；回退事件也可提醒；目标发布已变化时409并重查。
- [ ] 实现独立个人资源与作品覆盖；旧作品未选资源继续沿用旧快照。
- [ ] GREEN：服务、权限与更新提醒接口测试。

### Task 4: 写作与工具生效
Files: 修改 workflow/prompts.py、genre_catalog.py、reference_corpus.py、workflow/tools.py、生成任务受理与预算快照入口；新增 tests/test_writing_resource_runtime.py。
Interfaces: resolve_project_resources(project_id, selection_snapshot) 返回按作用环节组织的已授权内容；任务受理持久化资源快照，后续节点只读该快照。
- [ ] RED：stub provider捕获长短篇、规划、审核、全文/局部修订消息，只有选定版本生效。
- [ ] RED：运行中发布、回退或用户更换不影响当前任务；私有事实不跨作品；未选参考素材不能经只读工具旁路读取。
- [ ] 接通现有预算裁剪、题材和文风注入；同步可选表达规则的确定性校验适用方式，固定输出协议不变。
- [ ] GREEN：提示词、上下文预算、工具权限、长短篇与恢复相关定向测试。

### Task 5: 后台卡片、用户选择与提醒
Files: 扩展 web/src/pages/admin/PlatformResources.tsx 或拆分专门管理页、lib API；用户作品设置新增 WritingResourcePicker 和 ResourceUpdateDialog 及各自Vitest测试。
- [ ] RED：后台卡片编辑草稿、查看版本、发布、回退预览确认与并发错误保留草稿。
- [ ] RED：用户选择平台/个人资源，来源与版本可见；复制/个人编辑不会更新后台；弹窗关闭去重、主动更新勾选项、保留个人覆盖。
- [ ] 实现卡片式后台及用户入口，符合现有主题与移动端；不使用题材下拉作为资源管理界面。
- [ ] GREEN：完整前端 npm test、lint、build；浏览器核对管理员发布→用户选择→提示更新→拒绝/接受→后台回退链路。

## Final Verification
执行相关后端及隔离集成测试、契约无漂移检查、完整前端检查与diff检查。独立审查权限、快照、回退和运行时实际生效；修复重要问题后记录证据。没有运行的检查单独列出，不声称真实模型质量已验证。
