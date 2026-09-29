#!/bin/sh
# 首启建业务应用角色（只在全新数据卷上执行一次）。原为 01-roles.sql，改成 .sh 的唯一原因：
# 密码要从 MYINK_APP_PASSWORD 注入，好和 compose 里 API 的 DATABASE_URL 用同一个来源，
# 不至于在一处改了口令另一处没跟着改。SQL 本身逐字保留。
#
# 名字仍是固定的 myink / myink_app / 库 myink：只有口令是秘密，角色名不是。
# 注意：本文件只在空数据卷首次启动时跑；已有卷的 myink_app 口令不会被它改动。
#
# 不用 set -e：本文件可能被 entrypoint `source` 进同一个 shell（Windows 检出后没有可执行位），
# 那时 set -e 会污染 entrypoint 后续命令；改成显式判错 + exit 1，失败一样是响亮地起不来。

if ! psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_password="${MYINK_APP_PASSWORD:-myink}" <<'SQL'
-- myink_app：非超级 + NOBYPASSRLS（受 RLS 约束，§14.1 坑 3：超级用户永远绕过 RLS，
-- 业务必须走受约束角色）。建表由 `myink init` 用超级用户 myink 执行（表 owner=myink），
-- ALTER DEFAULT PRIVILEGES 保证 myink 后续新建表自动授 DML 给 myink_app。
-- CREATE ON SCHEMA public：langgraph checkpointer（§6.7）用应用连接 saver.setup()
-- 建内部表（checkpoints/checkpoint_blobs/checkpoint_writes，§14 隔离清单，非租户表），
-- 应用角色须能在 public 建表（PG15+ public 默认对 PUBLIC 无 CREATE）。
CREATE ROLE myink_app LOGIN PASSWORD :'app_password' NOBYPASSRLS;
GRANT CONNECT ON DATABASE myink TO myink_app;
GRANT CREATE ON SCHEMA public TO myink_app;
ALTER DEFAULT PRIVILEGES FOR ROLE myink IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO myink_app;
ALTER DEFAULT PRIVILEGES FOR ROLE myink IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO myink_app;
SQL
then
    echo "myink: 建 myink_app 角色失败，数据库不会就绪" >&2
    exit 1
fi
