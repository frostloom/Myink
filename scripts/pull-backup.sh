#!/usr/bin/env bash
# Myink 备份的离机副本：把服务器 ~/myink/backups 里的产物拉到本机。
#
# 为什么要有这一步：备份和库在同一块盘上（都在服务器），挡不住整机故障或磁盘坏掉。
# 服务器上那份继续由 cron 每天出（见 docs/DEPLOY.md「备份与恢复」），这份是本机副本。
#
# 用法：bash scripts/pull-backup.sh
#   REMOTE      SSH 别名（默认 myink，见 ~/.ssh/config）
#   REMOTE_DIR  服务器上的备份目录，相对该用户 home（默认 myink/backups）
#   LOCAL_DIR   本机落地目录（默认 ~/myink-backups）
#   KEEP        本机 myink-*.sql.gz 保留几份（默认 14）
#
# 本机侧建议也挂个定时任务（macOS launchd / cron），否则「备份没跑」这件事本身不会被发现。
set -euo pipefail

REMOTE="${REMOTE:-myink}"
REMOTE_DIR="${REMOTE_DIR:-myink/backups}"
LOCAL_DIR="${LOCAL_DIR:-$HOME/myink-backups}"
KEEP="${KEEP:-14}"

mkdir -p "$LOCAL_DIR"

# 路径故意写成相对形式：rsync 的远端路径默认相对该用户 home，这样不必把 /home/ubuntu 写死
# 在脚本里（换用户/换机器就失效）。不用 --delete：服务器轮转掉的旧份在本机多留一会儿，
# 本机自己按 KEEP 轮转。
rsync -az --include='*.sql.gz' --exclude='*' "$REMOTE:$REMOTE_DIR/" "$LOCAL_DIR/"

# 拉回来的每一份都过一遍解压校验。解不开的 .gz 比没有备份更危险——你以为有。
bad=0
for f in "$LOCAL_DIR"/*.sql.gz; do
    [ -e "$f" ] || continue
    if ! gzip -t "$f" 2>/dev/null; then
        echo "损坏：$f" >&2
        bad=1
    fi
done
[ "$bad" -eq 0 ] || { echo "拉取完成，但有损坏文件（见上）" >&2; exit 1; }

# 本机轮转：只动 myink- 开头的日常备份，手工的一次性备份（prod-*.sql.gz）不删。
ls -1t "$LOCAL_DIR"/myink-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "已同步到 ${LOCAL_DIR}："
ls -lh "$LOCAL_DIR"/*.sql.gz 2>/dev/null | awk '{print "  " $9 "  " $5}'