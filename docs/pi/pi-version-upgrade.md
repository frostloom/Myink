# Pinned administrator engine runtime

The integrated administrator role is `myink-administrator`; `Engine` is its replaceable interface.
The implemented engine is Pi. The controller owns grants, cumulative budget, source evidence and
OS containment; Pi alone does not authorize development, heavy checks or release.

## Current pin and verified milestone

`@earendil-works/pi-coding-agent@1.1.0` runs through its shipped `dist/bundle/cli.js`.
The seven same-version siblings are pinned with root overrides, including `pi-telemetry`.
The full nonsecret manifest and lock are checked in under `ops/pi/runtime/`.
Lock SHA256: `fd0f5bd8aa13e01da8792b161d80502f32e1afd00103151fbcc21f4b3146785a`.
The graph contains 146 packages; 121 applicable Linux x64 packages were acquired.
All installed archive bytes matched their reviewed SHA512 SRI. The esbuild 0.28.2 Linux x64
binary and package-local Photon/QuickJS WASM assets were present. No lifecycle scripts ran.
Node is fixed to v24.16.0 and npm to 11.13.0 in the private E runtime.

Actual installed CLI help and one local Anthropic SSE text RPC succeeded. The run accepted
`started`, observed `agent_settled`, validated the newly persisted assistant message, confirmed
`clear_queue` then `abort`, and awaited owned Pi exit 0. It issued one mock request and zero paid
requests. Artifacts are private E evidence, not compatibility claims for a real provider.
RPC acceptance, `agent_end`, nonempty files, handled prompts, protocol failures or stale resumed
messages do not certify completion.

## Installation and upgrades

Use only the verified E-hosted `MyinkPiLab` Linux x64 guest; do not copy Windows node_modules.
`ops/pi/lab/install-pi.sh resolve` performs one fresh lock-only resolution with scripts disabled,
optionals included, official npm registry, engine-strict, no audit/fund and a 600 second deadline.
It caps npm to 1 GiB memory, zero swap and 0.5 CPU. STOP and review the full resolved/SRI graph,
engine/platform constraints and all eight pins before `acquire REVIEWED_LOCK_SHA256`.
The latter performs one immutable `npm ci --ignore-scripts --include=optional`. Copy the reviewed
manifest/lock into the private E project for replay. Never run a manual lifecycle fallback or
silently omit an applicable optional package. Upgrades require a new reviewed pin and complete
lock, byte checks and actual CLI/RPC proof; the model cannot self-upgrade the engine.

Every process receives private HOME/XDG/cache/temp/session and Node compile cache paths,
`PI_TELEMETRY=0`, install telemetry/analytics disabled, cache warming off, retries/compaction off,
explicit offline/resource flags and no tools, MCP, discovery or inherited provider credentials.
The sole explicit trusted `pi-wire-guard.mjs` extension permits text-only payloads, strips cache
hints and forces disabled thinking. The gateway independently validates and meters the wire.
The pinned SDK uses exactly `/v1/messages?beta=true`; the gateway accepts that fixed route and
forwards the canonical upstream `/v1/messages`, rejecting every other query.

## Native private state and actual mock replay

DrvFS allowed the nonroot process to create auth locks but rejected their timestamp heartbeat
with EPERM. Use a fresh native directory owned uid/gid 65534, mode 0700, inside the independently
verified Linux VHD at `E:/tools/myink-pi/runtime/wsl`; bind ONLY that run directory to its explicit
`/mnt/e/tools/myink-pi/runtime/<run>` path inside the service. Do not remount host drives, change
global metadata, run Pi as root, or expose credentials/state/backups/main checkout. The host bind
target is empty outside that service namespace. Export selected proof/session files from the
native backend to a separate E evidence snapshot after exit.

Prepare a trusted E controller copy of `engine.py`, `contracts.py`, `policy.py`, `pi_config.py`,
`pi_rpc.py`, the package initializer, `lab/pi-mock.py` and `lab/pi-wire-guard.mjs`.
Run `python3 /TRUSTED_E_CONTROLLER/ops/pi/lab/pi-mock.py /EXPLICIT_E_RUN` in a fresh owned systemd
unit, with User=nobody, Group=nogroup, MemoryMax=402653184, MemorySwapMax=0, CPUQuota=50%,
RuntimeMaxSec=120, NoNewPrivileges, ProtectSystem=strict, ProtectHome, only the run directory
writable, the exact native bind, and IPAddressDeny=any/IPAddressAllow=localhost. Mask host C,
main checkout, private credentials/state and backups. Sanitize the environment and disable
Python bytecode writes. Verify actual UID, cgroup membership/limits, owned Pi exit and network
filter support. `--diagnose` sends EOF without a prompt and records bounded redacted diagnostics.

Focused checks:

```text
python -m pytest ops/pi/tests/test_pi_rpc.py ops/pi/tests/test_pi_config.py ops/pi/tests/test_pi_preview.py -q
FIXED_E_NODE ops/pi/tests/pi-wire-guard.test.mjs
```

`lab/pi-preview.py` is the one-prompt read-only source analysis entry. It requires a hash-pinned
trusted source snapshot, reviewed policy, private scoped-token file and an already authorized
loopback budget gateway. It gives no tools and produces an evidence-backed JSON proposal; source
analysis is not measured runtime improvement, and new feature direction belongs to the owner.
Canonical billing comes from `E:/tools/myink-pi/state/ledger.sqlite`, never Pi's catalog counters.
Only root-reviewed read-only preview eligibility can enable that call. At most six combined
compatibility/analysis HTTP attempts consume the existing local-trial-1 quota, never a new scope.
One real readonly source analysis subsequently completed through the gateway; see
[the introduction record](pi-introduction-2026-10-11.md) and its redacted receipt. The canonical
ledger contains one attempt with unknown complete usage and a conservative 2016384-microyuan
reservation; actual spend is unknown. Full C14 acceptance remains pending complete billing
compatibility, tool lifecycle/reconciliation and all heavy/release prerequisites. These
text-only milestones grant no release authority.
