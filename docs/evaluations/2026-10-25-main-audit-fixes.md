# main 全仓审查修复交付 — 2026-10-25

先将修复前基线 `a96d63c5` 推送到 GitHub main，再逐项完成失败回归、修复、全量验证、提交和正常推送。
基线包含此前已验证的题材发布修复与管理员分支合并。本次没有混入 Pi，没有部署、发布或改动生产数据库；既有未跟踪 `.DS_Store` 保留。

## 原始 11 项问题

| 问题 | 修复提交 | 该项全量验证 |
|---|---|---|
| 删除章节误删作者人物基底 | `60d535cc` | Python 1869 passed |
| 修订审核收尾丢失刚批准的记忆 | `2f8aab02` | Python 1870 passed |
| retry/defer 先 ACK 导致丢消息 | `94fab1bd` | Python 1874 passed |
| 删除后的事实无法恢复 | `9b4515f9` | Python 1876 passed |
| 并发确认重复记忆、确认/拒绝竞争 | `8689e989` | Python 1878 passed |
| 章节关系变更失效后没有恢复保留关系 | `34b7959d` | Python 1881 passed |
| 审核摘要预算暂停后续跑卡住 | `be160af3` | Python 1882 passed |
| provider 丢失长度截断原因 | `73326e1a` | Python 1892 passed |
| 切书后旧生成回包和轮询污染新书 | `153fbfa7` | 前端 590 passed，lint/build 通过 |
| 输入过程丢失未完成条目、换行和分隔符 | `b8445071` | 前端 594 passed，lint/build 通过 |
| 设置页跨书迟到加载/保存污染当前书 | `5af0f27f` | 前端 597 passed，lint/build 通过 |

## 独立复核及补充修复

按 requesting-code-review 进行一次独立只读全范围审查；3 项 Important 和 1 项 Minor 均已修复，未再次派生复审。

- `c118e072`：审核收尾和普通重写按提案身份去重历史批准，未被替代的拒绝决定优先；旧批准不能复活已拒绝的恢复项。补充 3 项失败回归；全量 Python 1895 passed。
- `ffd9e460`：关系按有序关系对区分同章保留版本，不能从一条旧版本失效推断整个来源章已撤销。补充同章有限期关系重写回归；全量 Python 1896 passed。
- `a744a8f8`：同次抽取先去重提案，再进行一对一匹配；不同置信度的重复项不会重复送审，语义不同的相近事实仍保留。补充缺失/活性事实重复与不同事实保护；全量 Python 1899 passed。
- 本报告所在提交：外部用相同规范化内容替换输入时，按结构对象身份清除旧的未完成片段；本地编辑回声仍保留原文。补充 textarea/input 两项失败回归；前端 599 passed。

正式回归位于 tests/test_review_routing.py、tests/test_invalidation.py、tests/test_correction.py，以及 web/src/components/StructuredTextField.test.tsx。

## 最终验证与边界

- Python：1899 passed、1 skipped、5 xfailed、2 subtests passed、2 warnings。
- 前端：72 文件、599 项测试通过；lint 和生产构建通过，存在原有 Fast Refresh、依赖及产物体积警告。
- compileall、20 条审计案例与 40 条覆盖清单校验通过；OpenAPI 113 条路径导出后无差异。
- 最终 Python 与 Caddy 镜像构建通过。Docker Hub 元数据连接超时后，使用 Dockerfile 已支持的参数切换到相同版本的 ECR 基础镜像；未修改镜像版本。
- 数据库测试使用专用 Compose 项目 `myink-main-audit-fixes`，端口 45432/46380/45673。未运行占固定资源的 ci-local.sh；用隔离环境执行对应验证。完成后只清理该项目。
- 1 项 comparison 集成测试因缺少专用获批评测数据库身份跳过；5 项是既有冲突样本的预期失败，不计为通过。仓库无 gateway，Go 检查不适用。
- 未进行真实付费模型调用、生产流量或真实 broker 崩溃压力验收；未以单测替代这些保证。未确认 GitHub Actions 的远程完成状态。

## 执行选择及兼容性

1. 按用户明确授权直接在 main 串行修复并推送，不另建分支或中途询问；变更立即同步共享 main，可按提交回退。
2. 全量验证在提交前执行，随后把实际 SHA 写入执行记录，避免提交未通过版本；脚本最初记录的提交区间已按真实 SHA 修正。
3. 作者及来源不明的历史人物保留。新增 nullable characters.source_chapter，通过既有 `myink init` 幂等补列；本次只升级隔离测试库，部署前仍需运行该既有初始化入口。
4. 关系关闭来源记录在已有 properties 中；未知历史关闭原因保持关闭，保护自然到期和作者明确删除。代价是含糊历史可能需要人工校正。
5. 审核续跑实际入口是 worker/processor.py，补充 typed checkpoint 阶段；缺少新标记的旧待审核检查点仍可走原恢复入口。代价是需要保留检查点兼容性。
6. error-finalization 永久卡死猜测经真实调用链核对撤回：未确认章节让摘要短路，下一次仍可 resolve_review；没有把缺少证据的猜测当作已修复问题。
7. 没有运行的真实崩溃、供应商和视觉条件不声称通过；计划文档空行不作为功能缺陷扩大清理范围。
8. 低风险输入重置也按用户“全部修复”的要求完成。当前 NewProject/Plan 保留解析结果的对象引用；未来若接入会克隆每次本地回声的消费者，应提供显式重置身份，避免把回声当成外部替换。

没有遗留已接受的审查问题。后续生产部署不在本次授权内。
