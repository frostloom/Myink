"""本地 embedding（§5.2 pgvector 一库多用）。

DeepSeek 官方无 embedding 接口（实测 /v1/embeddings 404），故本地加载
BAAI/bge-m3（中英双语，C-MTEB 中文检索榜单领先，1024 维与 embeddings 表
Vector(1024) 匹配）。本机 torch+CUDA 已装，GPU 推理单次几十毫秒，离线免费。

隔离与降级（§14.1 坑 1 + §6.12）：
- 向量召回是「加分项」，关系链路是主链路——encode/search 失败一律降级，
  不阻塞生成（try/except 在调用方）；
- 模型延迟加载：首次 encode 才 import sentence-transformers 并下载模型，
  测试环境（无该依赖）也能 import 本模块。

稳定性坑（sentence-transformers 5.x）：模型加载时即使已缓存也会向 Hub 探测
adapter_config.json（HTTP HEAD），国内网络不通会卡住重试几十秒 → 加载一律
`local_files_only=True` 纯离线（缓存缺失抛异常，由调用方降级记日志）。
首次需下载时：临时置 `HF_HUB_OFFLINE=0` + `EMBED_ALLOW_DOWNLOAD=1`。
"""

from __future__ import annotations

import logging
import os
import threading

from aiink.config import settings

logger = logging.getLogger(__name__)

# 国内镜像：huggingface.co 直连被墙，hf-mirror.com 可访问（实测 200）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_ENDPOINT", "https://hf-mirror.com")

EMBED_DIM = 1024


class Embedder:
    """文本向量化（bge-m3，1024 维）。测试可注入假实现或直接 monkeypatch get_embedder。"""

    def __init__(self, model_name: str | None = None, device: str | None = None,
                 allow_download: bool | None = None):
        self._model_name = model_name or settings.embed_model_name
        self._device = device or settings.embed_device
        # 默认纯离线（模型已缓存时不触网探测 adapter，防卡死）；下载开关走配置
        self._allow_download = settings.embed_allow_download if allow_download is None else allow_download
        self._model = None
        self._lock = threading.Lock()

    def _resolve_device(self) -> str:
        """auto → 有 CUDA 用 GPU，否则 CPU（部署到带 GPU 服务器自动切）。"""
        if self._device != "auto":
            return self._device
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from sentence_transformers import SentenceTransformer  # 延迟导入：测试环境不装也不崩

            device = self._resolve_device()
            logger.info("加载 embedding 模型 %s (device=%s, local_files_only=%s)...",
                        self._model_name, device, not self._allow_download)
            # local_files_only=True：缓存后纯离线加载，不再向 Hub 探测 adapter（sentence-transformers 5.x 坑）
            self._model = SentenceTransformer(self._model_name, device=device,
                                              local_files_only=not self._allow_download)
            logger.info("embedding 模型就绪")

    def encode(self, texts: list[str]) -> list[list[float]]:
        """批量向量化，返回 1024 维 float 列表；空输入返回空列表。"""
        if not texts:
            return []
        self._load()
        vecs = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [v.tolist() for v in vecs]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder
