# Pi 响应编码边界修复（2026-10-22）

前次真实请求200 SSE后UnicodeDecodeError；其Content-Encoding和原始响应未保存，真实根因仍未证实。离线gzip SSE复现确认现有raw转发会把压缩字节送到UTF-8解析器。HTTPX默认Accept-Encoding还会声明压缩支持，和这个转发边界不匹配。

两条生产入口（analysis_launcher._provider、control.serve_gateway）现在显式请求Accept-Encoding: identity。网关收到响应头后、读取正文前，仅允许缺省或identity编码；gzip/deflate/br/zstd、空值、叠加和未知编码均固定502，关闭上游、不重试，保留unknown完整预留。不增加自动解压，避免在现有大小检查前无界扩展。渐进流、绝对期限、usage严格校验和原计费规则不变。

私有best-effort usage诊断新增upstream_response：100–599整数状态码或null，以及有限编码类别（含absent/unavailable/other）。不保存原编码字符串、正文、凭据或异常文本。该诊断不证明实际花费或完整usage；上次unknown不会据此释放。

## 验证

新增测试先RED：16 failed、3 passed；其中正常identity兼容项在旧实现就通过，拒绝及协商项按预期失败。修复后149定向通过；完整Pi离线2042 passed、0 skipped、19项pi_lab/pi_live未选入（62.98秒），compileall、diff-check通过。独立只读审查Critical/Important/Minor均0，独立运行79项通过。未运行无关业务Python、Go、web和完整设施CI。

固定Linux ARM64 Node24.22.0/Pi1.1.0及既有镜像，外部HTTP边界用MockTransport，保留生产_provider函数、真实SQLite、loopback及容器执行：identity场景2 DONE/28 NOT_RUN，两新session/合同有效，每槽403/403/200/403，合成已知费用共1668 microyuan；两容器exit0删除、精确operation label为空。gzip场景上游忽略identity，恰好1次合成请求，502后1 UNCERTAIN/29 NOT_RUN，无UnicodeDecodeError，完整保留合成预留19384 microyuan；诊断明确gzip/unsupported_content_encoding，第二槽未启动，容器exit0删除且精确label为空。

验收过程保留失败证据：首次复制依赖解引用符号链接导致固定runtime SHA拒绝，尚未创建容器；改为保留原链接后使用新目录。gzip验收脚本最初误用真实策略预留金额，随后又遗漏合成策略cache_write最坏价格；通过只读检查已有合成账本校正为1000×3+2048×8=19384，再校验通过，未重跑容器/请求。上述均为验收准备或断言错误，未改生产预算规则。

本修复及合成验收0付费请求，未改canonical账本、凭据或全局live=false。机器记录见同名JSON。下一步以新run_id、新源码指纹及单独cap/deadline进行有限真实诊断；不恢复旧run、不自动重试、不释放旧unknown，不合并main或部署。真实provider是否遵守identity及usage语义仍待验证。
