# Mac Pi 离线基线恢复（2026-10-21）

在 Pi worktree、源码检查点 a0b8100 上恢复开发环境。使用已有 CPython3.12.15（Darwin arm64），独立 .venv；先安装pytest/httpx，再按CI安装 `uv pip install --python .venv/bin/python -e '.[dev]' -c docker/constraints.txt`。虚拟环境、依赖和原始日志均不入Git。本次没有启动真实Pi、模型请求或生产服务。

## 复现与根因

- 交接指定五个文件：106 passed，1.49秒。
- 初次完整离线测试因sqlalchemy/myink等项目依赖未安装，在收集阶段6 errors；这次没有算作通过。
- 补齐项目依赖后原有用例：23 failed、1715 passed、19 deselected，51.70秒。
- 15项备份协议夹具隐含运行者为Linux root；Mac普通用户在目标断言前被所有权检查拒绝。
- 5项slice/安装测试同样没有给临时目录中的模拟文件提供root身份。
- 2项B12回执测试模拟sys.platform=win32，却遗漏host_available_memory替身，落入Mac没有的ctypes.windll。
- 1项深JSON测试固定期待RecursionError；本机CPython解析该8000层合法JSON后由对象schema以ValueError拒绝。两条路径都保留整批unknown、原始字节和禁止执行。

## 修改和验证

只改四个测试文件。显式为选中的临时合成树提供st_uid=0；文件类型、mode、nlink和大小仍取真实stat；不改变生产root/文件/链接安全校验。只给两项模拟Windows回执补足内存替身；不改实际内存采样。深JSON断言接受两种等价拒绝类型，保留原始回执与权限断言。

- 四文件定向：139 passed，1.57秒；独立审查另运行139 passed，无发现。
- 原有完整离线基线：1738 passed、0 skipped、19 deselected，69.87秒。

命令：

```sh
.venv/bin/python -m pytest ops/pi/tests/ --ignore=ops/pi/tests/test_analysis_run.py -q -m 'not pi_lab and not pi_live' --tb=short --junitxml=.local/pi-durable-slots/baseline-offline-fixed.xml
```

显式排除本轮尚未提交的新槽位用例，便于分别验收环境恢复与新功能。19项pi_lab/pi_live未选入，不记为通过。没有运行完整业务CI、真实Linux root/systemd或Windows宿主验收。

私有原始记录在当前worktree的 `.local/pi-durable-slots/`：baseline-targeted.log、baseline-offline.log（收集错误）、baseline-offline-restored.log/xml（23失败）、portability-green.log、baseline-offline-fixed.log/xml（通过）。

## 原23项失败清单

- `ops/pi/tests/test_backup_lab.py::test_protocol_probe_retains_partial_output_on_child_timeout`
- `ops/pi/tests/test_backup_lab.py::test_protocol_workspace_is_fixed_native_and_refuses_preexisting`
- `ops/pi/tests/test_backup_lab.py::test_protocol_archive_verifies_members_and_preserves_native`
- `ops/pi/tests/test_backup_lab.py::test_protocol_archive_refuses_hardlink_or_budget`
- `ops/pi/tests/test_backup_lab.py::test_protocol_tmp_fixture_has_no_alias_and_refuses_unknown_or_duplicate`
- `ops/pi/tests/test_backup_lab.py::test_protocol_tmp_fixture_refuses_changed_operation_and_foreign_root`
- `ops/pi/tests/test_backup_lab.py::test_protocol_final_guard_allows_observation_change`
- `ops/pi/tests/test_backup_lab.py::test_protocol_final_guard_refuses_safety_or_unknown_drift[identity]`
- `ops/pi/tests/test_backup_lab.py::test_protocol_final_guard_refuses_safety_or_unknown_drift[cap]`
- `ops/pi/tests/test_backup_lab.py::test_protocol_final_guard_refuses_safety_or_unknown_drift[config]`
- `ops/pi/tests/test_backup_lab.py::test_protocol_final_guard_refuses_safety_or_unknown_drift[unknown_outer]`
- `ops/pi/tests/test_backup_lab.py::test_protocol_final_guard_refuses_safety_or_unknown_drift[unknown_proof]`
- `ops/pi/tests/test_backup_lab.py::test_protocol_final_guard_refuses_safety_or_unknown_drift[memory_events]`
- `ops/pi/tests/test_backup_lab.py::test_protocol_final_guard_refuses_safety_or_unknown_drift[path]`
- `ops/pi/tests/test_backup_lab.py::test_protocol_final_guard_refuses_safety_or_unknown_drift[membership]`
- `ops/pi/tests/test_executor.py::test_b12_probe_binds_approved_operation_and_native_blocked_receipt[blocked-done]`
- `ops/pi/tests/test_executor.py::test_b12_probe_binds_approved_operation_and_native_blocked_receipt[uncertain-uncertain]`
- `ops/pi/tests/test_feedback_evidence_v2.py::test_deep_valid_json_is_retained_as_whole_batch_unknown`
- `ops/pi/tests/test_probe_revision.py::test_new_slice_is_journaled_and_configured_before_start`
- `ops/pi/tests/test_probe_revision.py::test_partial_install_retains_original_bytes_and_durable_fence[replace]`
- `ops/pi/tests/test_probe_revision.py::test_partial_install_retains_original_bytes_and_durable_fence[final_health]`
- `ops/pi/tests/test_probe_revision.py::test_partial_install_retains_original_bytes_and_durable_fence[fence_mismatch]`
- `ops/pi/tests/test_probe_revision.py::test_partial_install_retains_original_bytes_and_durable_fence[success]`
