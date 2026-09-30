#!/usr/bin/env bash
# 给**已存在**的数据卷补建只读报表角色 myink_report。
#
# 为什么需要单独一个脚本：docker/initdb/01-roles.sh 只在空数据卷首次启动时执行，已经在跑的
# 库不会再跑一遍。服务器 ~/myink 没有源码、不是 git 仓库，所以这个文件要单独拷过去
# （和 backup.sh / docker-compose.yml 一样，见 docs/DEPLOY.md）。
#
# 用法（在服务器 ~/myink 目录下）：
#   MYINK_REPORT_PASSWORD='<强随机值>' bash create-report-role.sh
# 口令必须与 .env 里的 MYINK_REPORT_PASSWORD 一致，否则 myink-api 连不上报表库。
#
# 幂等：角色已存在时只重设口令与权限。
set -euo pipefail

: "${MYINK_REPORT_PASSWORD:?先设 MYINK_REPORT_PASSWORD（要和 .env 里那个一致）}"

# 口令不走命令行参数明文，而是从环境读进 psql 变量（容器内 pg_hba 对本地 socket 是 trust，
# 无需 PGPASSWORD）。注意 psql 在 dollar-quoted 串里不做变量替换，所以 CREATE ROLE 与
# ALTER ROLE ... PASSWORD 必须分两步写。
sudo docker compose exec -T \
    myink-pg psql -v ON_ERROR_STOP=1 --username myink --dbname myink \
    -v report_password="$MYINK_REPORT_PASSWORD" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'myink_report') THEN
        CREATE ROLE myink_report;
    END IF;
END $$;

-- 只读 + 跨租户：BYPASSRLS 才能看到全部租户的行；作为交换，只授 SELECT，
-- 并把它自己的默认事务设成只读，写不进去任何东西。
ALTER ROLE myink_report LOGIN BYPASSRLS PASSWORD :'report_password';
ALTER ROLE myink_report SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE myink TO myink_report;
GRANT USAGE ON SCHEMA public TO myink_report;
-- 存量表直接授；后续新建的表由上面的默认权限兜住。
GRANT SELECT ON ALL TABLES IN SCHEMA public TO myink_report;
ALTER DEFAULT PRIVILEGES FOR ROLE myink IN SCHEMA public
    GRANT SELECT ON TABLES TO myink_report;
SQL

echo "myink_report 已就绪。确认 .env 里的 MYINK_REPORT_PASSWORD 与刚才传入的一致，再 up -d。"