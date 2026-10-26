# Pi大量异常反馈不淹没报告

003已产生5次补丁并实际运行226检查；47个Fact.status异常的原始trace先占满65536捕获上限，checker被停止，原协议未完成，候选不采纳。本轮先修控制器而非隐瞒错误：保持原65KiB/费用/认证边界，可信runner只输出一个结构化JSON，不输出unittest raw traceback或普通print，status只加入固定安全属性枚举。原始候选不在宿主执行。

1. 合成宿主独立子进程226cases/60长错误、长load_error、import/test stdout/stderr和敏感属性遮罩RED→GREEN。
2. 隔离Linux用新runner重现003未采纳候选，仍须完整226且47errors，safe typed反馈不能成pass；所有原校验和捕获限额保持。
3. 独立审查+完整Pi/Node；新代码闭包与新检查点/新身份再精确审查后继续真实Pi，旧003不复用。004仍从原宿主5fd93重新实现，保持catalog errors0，不把003错误半成品包装成可自动选题base；新轮必须非空修复、unit＋最后status认证才能进入采纳审查。

独立审查P2：导入SystemExit绕过Exception并输出原始退出字符串；SystemExit/KeyboardInterrupt两项先RED后改为导入BaseException统一typed load_error，永不判pass。直接os.write或恶意重写stdlib仍由原捕获／隔离边界fail-closed，不宣称Python重定向能隔离这些行为。

真实SDK MOCK新增发现：检查完整返回约43.853秒，原extension所有工具30秒timer使SDK丢失已认证失败回执。仅run_check(unit)有限90秒，其他仍30秒，父开发deadline/捕获30秒/总额度不变；Node先RED再改。旧模拟001含1个模拟unknown保留，不影响真实账本；新模拟002新身份验证失败→修正→成功，不能重用旧模拟/真实身份。
