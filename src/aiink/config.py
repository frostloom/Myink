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


# JWT 身份断言（§14.1 ③）：dev 默认密钥仅供本地开发/测试（Python 与 Go 网关共享同一
# 非空默认，两端的 HS256 签名才能互相验证）；APP_ENV=prod 时 validate 拒绝该默认值。
_DEV_JWT_SECRET = "dev-jwt-secret-change-me"


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "dev") or "dev")
    # 应用连接角色：非超级、NOBYPASSRLS（§14.1 坑：超级用户永远绕过 RLS）
    database_url: str = field(
        default_factory=lambda: _env(
            "DATABASE_URL",
            "postgresql+psycopg://aiink_app:aiink@localhost:5432/aiink",
        )
        or "postgresql+psycopg://aiink_app:aiink@localhost:5432/aiink"
    )
    # DDL/迁移连接角色：表 owner 超级用户（仅 init/迁移/RLS 使用，业务不碰）
    admin_database_url: str = field(
        default_factory=lambda: _env(
            "ADMIN_DATABASE_URL",
            "postgresql+psycopg://aiink:aiink@localhost:5432/aiink",
        )
        or "postgresql+psycopg://aiink:aiink@localhost:5432/aiink"
    )
    deepseek_api_key: str = field(default_factory=lambda: _env("DEEPSEEK_API_KEY", "") or "")
    deepseek_base_url: str = field(default_factory=lambda: _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com") or "https://api.deepseek.com")
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
    recall_token_budget: int = 12_000
    max_revisions: int = 2  # rewrite 轮次上限（spec/state-flow.md §3）
    max_replans: int = 1  # replan 轮次上限（重规划比重写贵，预算更紧，§6.5）
    max_tool_calls: int = 3  # 只读查证工具执行总数预算（§10：audit/write 工具循环封顶）
    batch_max_default: int = 5  # 批次上限默认（plan.md §6.11）
    batch_max_hard: int = 20  # 批次硬上限
    # 长线治理全局审计（§8.6）：每 K 章一次跨章抽样 L2（batch_end 触发，窗口 < K 短路零成本）
    audit_interval: int = field(default_factory=lambda: int(_env("AUDIT_INTERVAL", "10") or "10"))

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
    api_host: str = field(default_factory=lambda: _env("API_HOST", "127.0.0.1") or "127.0.0.1")
    api_port: int = field(default_factory=lambda: int(_env("API_PORT", "8100") or "8100"))
    # 阶段 2 展示前端：网关唯一入口（app.py 生成走网关异步，§17.2）
    gateway_url: str = field(default_factory=lambda: _env("GATEWAY_URL", "http://localhost:8080") or "http://localhost:8080")

    # 阶段 3：JWT 身份断言（§14.1 ③，替换 X-AiInk-User 占位）。密钥与 Go 网关共享同一 .env，
    # dev 非空默认保证两端签名互通；prod 由 validate 强制显式密钥。
    jwt_secret: str = field(default_factory=lambda: _env("JWT_SECRET", _DEV_JWT_SECRET) or _DEV_JWT_SECRET)
    jwt_ttl: int = field(default_factory=lambda: int(_env("JWT_TTL", "1800") or "1800"))  # 秒，短时效（§14.2 SSO/token）

    def is_prod(self) -> bool:
        return self.app_env == "prod"

    def validate(self) -> None:
        if self.is_prod() and not self.deepseek_api_key:
            raise RuntimeError("APP_ENV=prod 时 DEEPSEEK_API_KEY 不能为空")
        if self.is_prod() and self.jwt_secret == _DEV_JWT_SECRET:
            raise RuntimeError("APP_ENV=prod 时 JWT_SECRET 不能为 dev 默认值（生产密钥需显式注入）")


settings = Settings()
settings.validate()  # prod 缺 DEEPSEEK_API_KEY 时导入即失败（评审 A5 fail-fast，§17.2）
