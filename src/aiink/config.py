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
    # 默认离线加载（模型缓存后不触网探测 adapter，防 sentence-transformers 5.x 卡死）；
    # 首次下载模型时设 EMBED_ALLOW_DOWNLOAD=1
    embed_allow_download: bool = field(default_factory=lambda: _env("EMBED_ALLOW_DOWNLOAD", "0") == "1")

    # 单章写作 token 预算（plan.md §7.4 分层召回预算）
    recall_token_budget: int = 12_000
    max_revisions: int = 2  # rewrite 轮次上限（spec/state-flow.md §3）
    max_replans: int = 1  # replan 轮次上限（重规划比重写贵，预算更紧，§6.5）
    batch_max_default: int = 5  # 批次上限默认（plan.md §6.11）
    batch_max_hard: int = 20  # 批次硬上限

    def is_prod(self) -> bool:
        return self.app_env == "prod"

    def validate(self) -> None:
        if self.is_prod() and not self.deepseek_api_key:
            raise RuntimeError("APP_ENV=prod 时 DEEPSEEK_API_KEY 不能为空")


settings = Settings()
