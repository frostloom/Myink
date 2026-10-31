#!/bin/bash
set -euo pipefail
# Called only after Windows proved this NEW import and E-hosted VHD ownership.
[[ $(id -u) == 0 && ! -e /var/lib/docker/engine-id && ! -e /etc/docker/daemon.json ]]
. /etc/os-release
[[ $ID == ubuntu && $VERSION_CODENAME == noble && $(dpkg --print-architecture) == amd64 ]]
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg iptables python3 python3-venv
install -m 0755 -d /etc/apt/keyrings
curl --proto '=https' --tlsv1.2 --fail --location https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
fingerprint=$(gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | awk -F: '$1=="fpr" {print $10;exit}')
[[ $fingerprint == 9DC858229FC7DD38854AE2D88D81803C0EBFCD88 ]]
chmod 644 /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
version='5:29.1.3-1~ubuntu.24.04~noble'
apt-get install -y --no-install-recommends "docker-ce=$version" "docker-ce-cli=$version" containerd.io docker-buildx-plugin=0.30.1-1~ubuntu.24.04~noble docker-compose-plugin
mkdir -p /etc/docker /opt/myink-pi-cache
cat > /etc/docker/daemon.json <<'EOF'
{"data-root":"/var/lib/docker","exec-opts":["native.cgroupdriver=systemd"]}
EOF
# Ubuntu WSL image boots systemd. If unavailable fail without shutting down any distribution.
[[ $(ps -p 1 -o comm=) == systemd && -f /sys/fs/cgroup/cgroup.controllers ]]
systemctl enable --now docker
[[ $(docker --host unix:///var/run/docker.sock info --format '{{.ServerVersion}}/{{.CgroupVersion}}/{{.CgroupDriver}}') == 29.1.3/2/systemd ]]
docker --host unix:///var/run/docker.sock info --format '{{json .}}'
