"""阶段 2 Python API：业务同步端点（§阶段2；:8100，只在容器网络内监听）。

职责（plan.md §17.2 三进程拓扑）：同步 CRUD / 任务详情（agent_runs 时间线）/
批次控制（pause/resume/cancel）/ 入队与三层闸门。Caddy 是唯一公网入口：按路径把
/api/v1/tasks/*/events 分给 Go 网关，其余业务路由直达本服务并在此验 JWT。
"""
