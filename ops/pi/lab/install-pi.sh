#!/bin/bash
# Lock resolution and acquisition are separate reviewed operations. No lifecycle scripts.
set -euo pipefail
mode=${1:?resolve or acquire}; expected=${2:-}
[[ $mode == resolve || $mode == acquire ]] || exit 64
[[ $(uname -sm) == 'Linux x86_64' && $(id -u) == 0 ]] || exit 65
base=/mnt/e/tools/myink-pi
node=$base/runtime/node/node-v24.16.0-linux-x64
project=$base/runtime/pi-project
[[ $($node/bin/node --version) == v24.16.0 ]]
[[ $(df -Pk "$base" | awk 'NR==2 {print $4}') -ge 7340032 ]]
mkdir -p "$project" "$base/runtime/npm-private" "$base/evidence/c14"
umask 077
exec 9>"$base/runtime/npm-private/acquisition.lock"
flock -n 9 || exit 73
if [[ $mode == resolve ]]; then
  [[ ! -e $project/package-lock.json && ! -e $project/node_modules ]]
  cat > "$project/package.json" <<'JSON'
{"name":"myink-private-pi-runtime","version":"0.0.0","private":true,"type":"module","dependencies":{"@earendil-works/pi-coding-agent":"1.1.0"},"overrides":{"@earendil-works/pi-coding-agent":"1.1.0","@earendil-works/chord":"1.1.0","@earendil-works/pi-agent-core":"1.1.0","@earendil-works/pi-ai":"1.1.0","@earendil-works/pi-codemode":"1.1.0","@earendil-works/pi-mcp":"1.1.0","@earendil-works/pi-tui":"1.1.0","@earendil-works/pi-telemetry":"1.1.0"}}
JSON
  action=(install --package-lock-only)
else
  [[ $expected =~ ^[a-f0-9]{64}$ && -f $project/package-lock.json && ! -e $project/node_modules ]]
  [[ $(sha256sum "$project/package-lock.json" | cut -d' ' -f1) == "$expected" ]]
  action=(ci)
fi
for path in home config cache data tmp compile-cache npm-cache; do mkdir -p "$base/runtime/npm-private/$path"; done
unit=myinkpi-c14-npm-$mode-$(cat /proc/sys/kernel/random/uuid)
printf '%s\n' "$unit" > "$base/evidence/c14/npm-$mode-unit.txt"
systemd-run --quiet --wait --pipe --collect --unit="$unit" --description="C14 exact npm $mode" \
  --service-type=exec -p MemoryMax=1073741824 -p MemorySwapMax=0 -p CPUQuota=50% -p RuntimeMaxSec=600 \
  -p KillMode=control-group -p NoNewPrivileges=yes -p WorkingDirectory="$project" \
  /usr/bin/env -i PATH="$node/bin:/usr/bin:/bin" HOME="$base/runtime/npm-private/home" \
  XDG_CONFIG_HOME="$base/runtime/npm-private/config" XDG_CACHE_HOME="$base/runtime/npm-private/cache" \
  XDG_DATA_HOME="$base/runtime/npm-private/data" TMPDIR="$base/runtime/npm-private/tmp" \
  TMP="$base/runtime/npm-private/tmp" TEMP="$base/runtime/npm-private/tmp" \
  NODE_COMPILE_CACHE="$base/runtime/npm-private/compile-cache" PI_TELEMETRY=0 \
  npm_config_cache="$base/runtime/npm-private/npm-cache" npm_config_update_notifier=false \
  "$node/bin/node" "$node/lib/node_modules/npm/bin/npm-cli.js" "${action[@]}" \
  --ignore-scripts --include=optional --registry=https://registry.npmjs.org --audit=false --fund=false \
  --engine-strict --fetch-retries=0 --fetch-timeout=30000 2>&1 | tee "$base/evidence/c14/npm-$mode.log"
sha256sum "$project/package.json" "$project/package-lock.json" > "$base/evidence/c14/npm-$mode-hashes.txt"
