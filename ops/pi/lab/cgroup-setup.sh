#!/bin/bash
set -euo pipefail
[[ $(id -u) == 0 && $(docker --host unix:///var/run/docker.sock info --format '{{.ID}}') == 364e8400-3844-47e2-b86d-8b626332f61c ]]
mkdir -p /etc/systemd/system
for kind in agent heavy infra; do
  case "$kind" in
    agent) memory=402653184; swap=0; cpu=50% ;;
    heavy) memory=1610612736; swap=268435456; cpu=200% ;;
    infra) memory=805306368; swap=0; cpu=100% ;;
  esac
  cat > "/etc/systemd/system/myinkpi-$kind.slice" <<EOF
[Unit]
Description=Private Myink Pi $kind accounting
[Slice]
MemoryAccounting=yes
CPUAccounting=yes
MemoryMax=$memory
MemorySwapMax=$swap
CPUQuota=$cpu
CPUQuotaPeriodSec=100ms
EOF
  systemctl daemon-reload
  systemctl start "myinkpi-$kind.slice"
done
