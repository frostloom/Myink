#!/usr/bin/env bash
# Myink 数据库备份：pg_dump 一份 + 轮转保留最近 N 份。
#
# 跑在服务器上，由 cron 每天调一次。服务器 ~/myink 没有源码、不是 git 仓库，
# 这个脚本要单独拷过去（和 docker-compose.yml 一样，见 docs/DEPLOY.md）。
#
# 用法：bash backup.sh
#   COMPOSE_DIR  服务器上的 compose 目录（默认 ~/myink）
#   BACKUP_DIR   备份落盘目录（默认 $COMPOSE_DIR/backups）
#   KEEP         保留最近几份（默认 14）
#
# 注意：备份落在同一块盘上，挡不住整机故障。离机副本见 docs/REMAINING-WORK.md §2.1。
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-$HOME/myink}"
BACKUP_DIR="${BACKUP_DIR:-$COMPOSE_DIR/backups}"
KEEP="${KEEP:-14}"

# 服务器上 docker 要 sudo，开发机上不要——探测一次，别让脚本在两处写法不同。
# （`docker info` 不带 sudo 能通，就说明当前用户已在 docker 组里。）
if docker info >/dev/null 2>&1; then
    DOCKER=docker
else
    DOCKER="sudo docker"
fi

cd "$COMPOSE_DIR"
mkdir -p "$BACKUP_DIR"

stamp="$(date +%Y%m%d%H%M%S)"
out="$BACKUP_DIR/myink-$stamp.sql.gz"
tmp="$out.part"

# -T 不分配 tty（cron 里没有）。先写 .part 再改名：中途失败留下的半份不会被后续轮转
# 当成一份好备份，也不会被误拿去恢复。
if ! $DOCKER compose exec -T myink-pg pg_dump -U myink -d myink | gzip -1 > "$tmp"; then
    rm -f "$tmp"
    echo "备份失败：pg_dump 出错" >&2
    exit 1
fi
# gzip 收尾失败的残留同样按失败处理：解不开的 .gz 比没有备份更危险（以为有）。
if [ ! -s "$tmp" ] || ! gzip -t "$tmp" 2>/dev/null; then
    rm -f "$tmp"
    echo "备份失败：产物为空或损坏" >&2
    exit 1
fi
mv "$tmp" "$out"

# 轮转：只留最近 KEEP 份。用 .sql.gz 而不是 *.gz，免得把别的文件一起删掉。
ls -1t "$BACKUP_DIR"/myink-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

# 变量必须写成 ${out}：后面紧跟全角「（」，bash 会把多字节字符当成变量名的一部分，
# 报 `out: unbound variable`——备份明明成功，脚本却以失败退出，cron 那边会误告警。
echo "已备份 ${out}（$(du -h "$out" | cut -f1)）"