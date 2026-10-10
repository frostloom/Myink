#!/bin/sh
# 首启建业务角色（只在全新数据卷上执行一次）：myink_app（受 RLS 约束的读写角色）与
# myink_report（BYPASSRLS 的只读报表角色）。原为 01-roles.sql，改成 .sh 的唯一原因：
# 口令要从 MYINK_APP_PASSWORD / MYINK_REPORT_PASSWORD 注入，好和 compose 里的连接串用
# 同一个来源，不至于在一处改了口令另一处没跟着改。SQL 本身逐字保留。
#
# 名字仍是固定的 myink / myink_app / myink_report / 库 myink：只有口令是秘密，角色名不是。
# 注意：本文件只在空数据卷首次启动时跑；已有卷的角色不会被它创建或改动——
# 存量库要补 myink_report 请用 scripts/create-report-role.sh，见 docs/DEPLOY.md。
#
# 不用 set -e：本文件可能被 entrypoint `source` 进同一个 shell（Windows 检出后没有可执行位），
# 那时 set -e 会污染 entrypoint 后续命令；改成显式判错 + exit 1，失败一样是响亮地起不来。

if ! psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_password="${MYINK_APP_PASSWORD:-myink}" \
     -v report_password="${MYINK_REPORT_PASSWORD:-myink}" <<'SQL'
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

-- myink_report：只读报告角色，只给 /admin 的统计查询用（routes_admin.admin_read_session）。
-- 跨租户统计必须能看全部行，所以给它 BYPASSRLS——这一个特权换取的是「彻底摘掉写能力」：
-- 只授 SELECT，默认事务只读。即便报表那条路径被注入，也改不动任何一行。
-- 建表只发生在 myink init（超级用户 myink，表 owner=myink），故用 ALTER DEFAULT PRIVILEGES
-- 兜住后续新建的表；不授 CREATE，它自己建不了表。
CREATE ROLE myink_report LOGIN PASSWORD :'report_password' BYPASSRLS;
GRANT CONNECT ON DATABASE myink TO myink_report;
GRANT USAGE ON SCHEMA public TO myink_report;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO myink_report;
DO $$ BEGIN
    IF to_regclass('public.admission_intents') IS NOT NULL THEN
        REVOKE ALL ON public.admission_intents FROM myink_report;
    END IF;
  IF to_regclass('public.maintenance_executions') IS NOT NULL THEN
        REVOKE ALL ON public.maintenance_executions FROM myink_report;
    END IF;
END $$;
ALTER DEFAULT PRIVILEGES FOR ROLE myink IN SCHEMA public
    GRANT SELECT ON TABLES TO myink_report;
ALTER ROLE myink_report SET default_transaction_read_only = on;
SQL
then
    echo "myink: 建 myink_app / myink_report 角色失败，数据库不会就绪" >&2
    exit 1
fi
