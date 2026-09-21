"""阶段 2 Python API：业务同步端点（§阶段2；:8100，只在容器网络内监听）。

职责（plan.md §17.2 三进程拓扑）：同步 CRUD / 任务详情（agent_runs 时间线）/
批次控制（pause/resume/cancel）/ 入队与三层闸门 / SSE 进度流。Caddy 是唯一公网入口：
全部 /api/v1/* 都直达本服务，身份也由本服务自己验 JWT。
"""
