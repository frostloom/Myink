# Myink Python 镜像：myink-api（uvicorn）/ myink-worker（队列消费）共用。
# 只 COPY Python 侧（pyproject + src/），web/ 与 tests/ 不进镜像。
# 依赖全量安装（含 sentence-transformers/bge-m3，重但按 EMBED_ENABLED 开关加载，见 docker-compose.yml）。
#
# 基础镜像源可用 build arg 覆盖（国内 docker.io 直连可能超时；compose 当前环境传
# PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim，见 docker-compose.yml）。
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
WORKDIR /app

# pip 源可覆盖（国内 pypi.org 直连慢/不通，compose 传清华源，见 docker-compose.yml）
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY pyproject.toml ./
# 依赖锁：pyproject 里的 `>=` 是意图，这里才是**这次构建实际装了哪些版本**（含间接依赖）。
# 放在 src 之前：改代码不该让这一层失效，只有动依赖才重建。-c 是约束不是安装清单，
# 缺项不会被漏装——lock 与 pyproject 冲突时 pip 会直接报错，这正是想要的效果。
COPY docker/constraints.txt ./docker/constraints.txt
COPY src/ ./src/
# 装核心依赖（不含 ml extras——sentence-transformers/torch ~2GB 且国内源下载易抖，
# embedder 延迟导入 + EMBED_ENABLED=0 默认不加载，纯关系链路可用；需要时 pip install -e .[ml]）。
# cache mount：pip wheel 缓存跨 build 复用（网络抖动中断后重跑不重下已拉取部分）；
# --timeout/--retries 应对国内大依赖读超时抖动。lock 只覆盖核心依赖，加 ml extras 时先重新生成。
RUN --mount=type=cache,target=/root/.cache/pip pip install . -c docker/constraints.txt --index-url ${PIP_INDEX_URL} --timeout 120 --retries 5

# 镜像自洽：核心依赖不含 ml extras（torch/sentence-transformers），默认关闭向量
#（config.py 默认 enable=1 会去 import 未装的 torch 报错而非降级）；compose 可按需覆盖
ENV EMBED_ENABLED=0

# 非 root 运行。uid 固定 10001（镜像里写死，不随构建漂移）。两点注意：
# - /data/feedback 是 api 运行时**要写**的（用户反馈附件），compose 在这里挂了卷。
#   这里先建好并给对属主，**全新**命名卷会继承镜像目录的属主，不必手工处理；
#   已经存在的卷属主仍是 root，切换前要 chown 一次——见 docs/DEPLOY.md。
# - HOME 显式给到新家目录：非 root 进程的默认 HOME 仍是 /root，开本地 embedding 时
#   模型缓存会写不进去。
RUN useradd --create-home --uid 10001 --user-group myink \
    && mkdir -p /data/feedback \
    && chown -R myink:myink /data
ENV HOME=/home/myink
USER 10001

EXPOSE 8100
# 构建来源自证。放在最后一层：改 commit 只让这一层失效，前面的依赖层照旧复用。
# compose 传 GIT_REVISION=$(git rev-parse --short HEAD)，读法见 docs/DEPLOY.md。
# 没传就是 unknown——读出来是「这次没记」，而不是一个看着像真的假版本号。
ARG GIT_REVISION=unknown
LABEL org.opencontainers.image.revision=${GIT_REVISION}
# 默认入口；compose 中 myink-migrate 覆盖为 `myink init`，api 为 `myink-api`，worker 为 `myink-worker`
CMD ["myink-api"]
