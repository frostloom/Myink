"""配置加载（plan.md §17.2：环境变量分层，dev/test/prod）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# 从项目根目录 .env 加载（密钥不进代码库）
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")


def _env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


# JWT 身份断言（§14.1 ③）：dev 默认密钥仅供本地开发/测试；APP_ENV=prod 时 validate
# 拒绝该默认值。签发与验签同一个进程，不再有「两端密钥必须一致」的隐式约束。
_DEV_JWT_SECRET = "dev-jwt-secret-change-me"


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "dev") or "dev")
    # 应用连接角色：非超级、NOBYPASSRLS（§14.1 坑：超级用户永远绕过 RLS）
    database_url: str = field(
        default_factory=lambda: _env(
            "DATABASE_URL",
            "postgresql+psycopg://myink_app:myink@localhost:5432/myink",
        )
        or "postgresql+psycopg://myink_app:myink@localhost:5432/myink"
    )
    # DDL/迁移连接角色：表 owner 超级用户（仅 init/迁移/RLS 使用，业务不碰）
    admin_database_url: str = field(
        default_factory=lambda: _env(
            "ADMIN_DATABASE_URL",
            "postgresql+psycopg://myink:myink@localhost:5432/myink",
        )
        or "postgresql+psycopg://myink:myink@localhost:5432/myink"
    )
    # 项目自定义模型密钥的静态加密主密钥；空值时沿用 JWT_SECRET 派生密钥以兼容本地部署。
    model_credential_key: str = field(default_factory=lambda: _env("MODEL_CREDENTIAL_KEY", "") or "")
    self_host_url: str = field(default_factory=lambda: _env("SELF_HOST_URL", "") or "")
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO") or "INFO")

    # 本地 embedding（§5.2 一库多用）：bge-m3 中英双语，1024 维与 embeddings 表 Vector(1024) 匹配
    # DeepSeek 官方无 embedding 接口（实测 /v1/embeddings 404），故本地加载，离线免费。
    # device: auto=有 CUDA 用 GPU 否则 CPU（实测 CPU encode ~0.6s/次，MVP 每章 2 次可接受）
    embed_model_name: str = field(default_factory=lambda: _env("EMBED_MODEL_NAME", "BAAI/bge-m3") or "BAAI/bge-m3")
    embed_device: str = field(default_factory=lambda: _env("EMBED_DEVICE", "auto") or "auto")
    # 低内存/CI 关闭开关：向量是加分项（§14.1 坑 1），EMBED_ENABLED=0 时不加载
    # bge-m3（CPU 约 2.2GB），encode 立即抛错由调用方降级走纯关系链路
    embed_enabled: bool = field(default_factory=lambda: _env("EMBED_ENABLED", "1") == "1")
    # 默认离线加载（模型缓存后不触网探测 adapter，防 sentence-transformers 5.x 卡死）；
    # 首次下载模型时设 EMBED_ALLOW_DOWNLOAD=1
    embed_allow_download: bool = field(default_factory=lambda: _env("EMBED_ALLOW_DOWNLOAD", "0") == "1")

    # 单章写作 token 预算（plan.md §7.4 分层召回预算）
    recall_token_budget: int = field(default_factory=lambda: int(_env("RECALL_TOKEN_BUDGET", "12000") or "12000"))
    # 完整请求（正文、提示词、记忆、工具）的独立上限；召回预算不能充当正文预算。
    request_token_budget: int = field(default_factory=lambda: int(_env("REQUEST_TOKEN_BUDGET", "64000") or "64000"))
    max_revisions: int = 2  # rewrite 轮次上限（spec/state-flow.md §3）
    max_patches: int = 2  # 局部补丁独立预算，不占用全章重写轮次
    max_replans: int = 1  # replan 轮次上限（重规划比重写贵，预算更紧，§6.5）
    max_tool_calls: int = 3  # 只读查证工具执行总数预算（§10：audit/write 工具循环封顶）
    batch_max_default: int = 5  # 批次上限默认（plan.md §6.11）
    batch_max_hard: int = field(default_factory=lambda: int(_env("BATCH_MAX_HARD", "20") or "20"))  # 批次硬上限
    # 三层闸门（§13，gates.lua）参数：env 名与默认值照抄网关 config.go，让 .env 保持
    # 单一真源；Go 退场后这里是唯一读取方。CONCURRENCY_LIMIT 刻意不搬——gates.lua 里
    # 并发判定是硬编码的 `inflight > 0`，那个配置项从来没人读（网关侧也一样），
    # 搬过来只会让人以为并发数可调。
    quota_daily: int = field(default_factory=lambda: int(_env("QUOTA_DAILY_CHAPTERS", "500") or "500"))
    book_quota_daily: int = field(default_factory=lambda: int(_env("BOOK_QUOTA_DAILY_CHAPTERS", "50") or "50"))
    daily_budget: float = field(default_factory=lambda: float(_env("DAILY_BUDGET_YUAN", "2.0") or "2.0"))
    cost_per_chapter: float = field(default_factory=lambda: float(_env("COST_PER_CHAPTER_YUAN", "0.05") or "0.05"))
    # 无 task 的账号对话/文风提取：共享日成本，独立调用数和单用户并发租约。
    account_model_calls_daily: int = field(default_factory=lambda: int(_env("ACCOUNT_MODEL_CALLS_DAILY", "60") or "60"))
    account_model_lease_seconds: int = field(default_factory=lambda: int(_env("ACCOUNT_MODEL_LEASE_SECONDS", "900") or "900"))
    account_model_unknown_cost: float = field(default_factory=lambda: float(_env("ACCOUNT_MODEL_UNKNOWN_COST_YUAN", "0.05") or "0.05"))
    # 入队消息的 RabbitMQ 优先级（tier=vip 插队；主队列 x-max-priority=10）
    priority_vip: int = field(default_factory=lambda: int(_env("PRIORITY_VIP", "9") or "9"))
    priority_normal: int = field(default_factory=lambda: int(_env("PRIORITY_NORMAL", "0") or "0"))
    # 长线治理全局审计（§8.6）：每 K 章一次跨章抽样 L2（batch_end 触发，窗口 < K 短路零成本）
    audit_interval: int = field(default_factory=lambda: int(_env("AUDIT_INTERVAL", "30") or "30"))
    # 单章流 Reflexion 复盘（§8.9 扩展）：每 N 章对窗口内章节做一次复盘提炼（批次流走 batch_end）
    chapter_reflexion_interval: int = 5
    # 每日新建作品数上限（plan.md §13 三层闸门 bookcnt）：建书端点独立校验（生成入队时
    # 网关 gates.lua rate:bookcnt 才触发，建书本身需在 Python 侧计数）。env 名与默认值
    # 对齐网关 config.go BooksPerDay（双端同 env 防漂移），超限返回 429 BOOK_CNT_EXCEEDED。
    books_per_day_max: int = field(default_factory=lambda: int(_env("BOOKS_PER_DAY", "10") or "10"))

    # 阶段 2：Redis 队列 + worker（§阶段2；§5.3 Redis 只管可重建数据，终态落 DB）
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6380/0") or "redis://localhost:6380/0")
    worker_stream: str = field(default_factory=lambda: _env("WORKER_STREAM", "queue:tasks") or "queue:tasks")
    worker_group: str = field(default_factory=lambda: _env("WORKER_GROUP", "workers") or "workers")
    worker_max_retries: int = field(default_factory=lambda: int(_env("WORKER_MAX_RETRIES", "3") or "3"))
    worker_backoff_base: int = field(default_factory=lambda: int(_env("WORKER_BACKOFF_BASE", "1") or "1"))  # 2^retry 秒退避
    worker_defer_backoff_s: int = field(default_factory=lambda: int(_env("WORKER_DEFER_BACKOFF_S", "5") or "5"))  # 书忙固定退避（不计 retry_count）
    # 租约锁（§6.12 崩溃恢复缺口修复）：锁 TTL 远小于网关认领阈值 MinIdle(120s)，
    # 崩溃后锁自过期早于认领；心跳续租间隔（秒），3× 间隔无心跳判僵尸可回收
    worker_inflight_ttl: int = field(default_factory=lambda: int(_env("WORKER_INFLIGHT_TTL", "60") or "60"))  # lock:task TTL（租约）
    worker_lock_heartbeat: int = field(default_factory=lambda: int(_env("WORKER_LOCK_HEARTBEAT", "15") or "15"))  # 持锁续租间隔
    worker_heartbeat_interval: int = field(default_factory=lambda: int(_env("WORKER_HEARTBEAT_INTERVAL", "5") or "5"))
    # 阶段 6：RabbitMQ 任务队列（替代 Redis Streams 主队列 + ZSET 延迟 + 网关 dispatcher）。
    # amqp_url 与网关 config.go AmqpURL 同值（compose 内 amqp://myink:myink@myink-rabbitmq:5672/）；
    # queue_prefix 仅测试隔离用（生产空串，拓扑名与网关端完全一致）。
    amqp_url: str = field(default_factory=lambda: _env("AMQP_URL", "amqp://guest:guest@localhost:5672/") or "amqp://guest:guest@localhost:5672/")
    queue_prefix: str = field(default_factory=lambda: _env("QUEUE_PREFIX", "") or "")
    api_host: str = field(default_factory=lambda: _env("API_HOST", "127.0.0.1") or "127.0.0.1")
    api_port: int = field(default_factory=lambda: int(_env("API_PORT", "8100") or "8100"))

    # 进程内全局令牌桶（等价网关 limiter.Middleware）：env 名与默认值照抄网关 config.go 的
    # RATE_PER_SEC / RATE_BURST，好让 .env 保持单一真源。粗粒度防刷；按用户的配额/并发/
    # 日成本走 gates.lua（§13）。uvicorn 单进程时额度与网关一致，加 workers= 会翻倍。
    rate_per_sec: int = field(default_factory=lambda: int(_env("RATE_PER_SEC", "20") or "20"))
    rate_burst: int = field(default_factory=lambda: int(_env("RATE_BURST", "40") or "40"))

    # 阶段 3：JWT 身份断言（§14.1 ③，替换 X-Myink-User 占位）。
    # dev 非空默认便于本地起步；prod 由 validate 强制显式密钥。
    jwt_secret: str = field(default_factory=lambda: _env("JWT_SECRET", _DEV_JWT_SECRET) or _DEV_JWT_SECRET)
    jwt_ttl: int = field(default_factory=lambda: int(_env("JWT_TTL", "1800") or "1800"))  # 秒，短时效（§14.2 SSO/token）

    # 阶段 3：扫榜（plan.md §10；上游不可信，榜单只作建书前的题材风向灵感工具、
    # 不进记忆/事实层、不注入任何生成节点）。默认开 + 优雅降级：
    # RANKINGS_ENABLED=0 完全关闭；网络不可达/无有效项 → 内置样例
    # （source=sample + error），面板照常展示不中断。
    rankings_enabled: bool = field(default_factory=lambda: _env("RANKINGS_ENABLED", "1") == "1")
    rankings_timeout: int = field(default_factory=lambda: int(_env("RANKINGS_TIMEOUT", "10") or "10"))  # 秒
    rankings_limit: int = field(default_factory=lambda: int(_env("RANKINGS_LIMIT", "10") or "10"))  # 展示条数 cap
    rankings_cache_ttl: int = field(default_factory=lambda: int(_env("RANKINGS_CACHE_TTL", "3600") or "3600"))  # 秒

    def is_prod(self) -> bool:
        return self.app_env == "prod"

    def validate(self) -> None:
        import math

        if self.account_model_calls_daily <= 0 or self.account_model_lease_seconds < 600:
            raise ValueError("ACCOUNT_MODEL_CALLS_DAILY 必须为正，ACCOUNT_MODEL_LEASE_SECONDS 至少 600")
        if not math.isfinite(self.account_model_unknown_cost) or self.account_model_unknown_cost <= 0:
            raise ValueError("ACCOUNT_MODEL_UNKNOWN_COST_YUAN 必须为有限正数")
        if self.request_token_budget <= 1000:
            raise ValueError("REQUEST_TOKEN_BUDGET 必须大于 1000")
        if self.recall_token_budget <= 1000:
            raise RuntimeError("RECALL_TOKEN_BUDGET 必须大于预留的 1000 tokens")
        if self.is_prod() and self.jwt_secret == _DEV_JWT_SECRET:
            raise RuntimeError("APP_ENV=prod 时 JWT_SECRET 不能为 dev 默认值（生产密钥需显式注入）")


settings = Settings()
settings.validate()
