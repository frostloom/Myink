# Guest mode verification — 2026-10-28

Implementation and final browser/frontend verification are complete. Changes remain uncommitted on `main`; no push, merge or deployment. Existing unrelated work was preserved. Independent task/final source review is recorded in `.superpowers/sdd/2026-10-28-guest-mode/`; detailed iteration evidence is in `task-4-report.md` and `final-fix-report.md` there.

## Final evidence

Commands ran from the repository root with Node24.22.0 and Python3.12. Database checks ran serially against dedicated Compose project `myink-guest-20261028`, PostgreSQL54012, Redis62043, RabbitMQ62045. Environment: `/tmp/myink-guest-20261028/env.sh` (test mode, dotenv disabled, embeddings/rankings disabled, SITE_ADDRESS=http://localhost). No production or real model calls.

| Check | Result | Evidence |
|---|---|---|
| Full Python before final narrow auth fix | 2095 passed,1 skipped,5 xfailed,2 warnings,1 AMQP teardown error,2 subtests passed; exit1 | `/tmp/myink-guest-task4-full.log` |
| Unchanged single multiprocess retry | 1 passed including teardown,63.44s,exit0 | `/tmp/myink-guest-task4-multiprocess-retry.log` |
| Final auth/guest/cookie/contract coverage | 112 passed,1 existing warning; fixture hermeticity follow-up15passed | `final-fix-work/main-auth-contract.log`, `main-hermetic-test.log` under the SDD directory |
| Fixture updates and permanent legacy migration regression | 46 passed,1 existing warning | `/tmp/myink-guest-task4-fixtures-green.log` |
| Full lint before the final rail-label supplement | 0 errors,9 existing Vue warnings | `/tmp/myink-guest-task4-final-source-lint.log` |
| Shared frontend tests | 34 files,207 passed | `/tmp/myink-guest-task4-shared.log` |
| Full Vue before the final rail-label supplement | 89 files,782 passed,0 skipped,75.99s | `/tmp/myink-guest-task4-final-source-vue.log` |
| Final label-build strict Vue/TS + Vite build | passed,846 modules; existing PostCSS/chunk warnings | `/tmp/myink-guest-task4-rail-build.log` |
| Browser cleanup/receipt/retained-assets helpers | 10 passed | `/tmp/myink-guest-task4-browser-helpers-final.log` |
| Verifier failure cleanup regressions | 3 Python stub tests +1 intentional missing-navigation browser test passed | `/tmp/myink-guest-task4-fix1-green.log`, `-fix1-browser-final.log` |
| Dependency audit | 0 vulnerabilities | `/tmp/myink-guest-task4-audit.log` |
| Pre-label Chromium/Firefox/WebKit matrix (after shared dialog fix) | 21/21 stages passed; guest9groups per engine; unknown APIs/page errors/cleanup errors all empty | `/tmp/myink-guest-task4-matrix-final/receipt.json` |
| Final label-build real isolated API + exact built UI | 4/4 groups passed; browser/proxy/API/accounts cleaned; logout visible | `/tmp/myink-guest-task4-real-rail-final/receipt.json`, `cleanup.json`, `api.log` |
| Rail-label supplement covering checks | 43 Vue tests, changed-file lint and strict typecheck passed | `final-fix-work/rail-label-green.log`, `rail-label-typecheck.log` under the SDD directory |
| Final API contract export/schema equality | 118 paths; anonymous-or-bearer registration covered | final112-test coverage above; `spec/api-openapi.json` |

The original Python aggregate is **not fully green**: the multiprocess test body passed, then module teardown timed out during AMQP handshake while purging only its isolated queues. No application assertion failed. Before retry, no pytest/test worker remained; dedicated RabbitMQ reported healthy, ping succeeded and a bounded read-only AMQP handshake/close succeeded (`/tmp/myink-guest-task4-broker-health.log`). Only the affected case was rerun, unchanged, and passed. No redundant full-suite repeat was performed. Final narrow auth/config changes were covered separately by112tests and the15-test hermeticity follow-up.

The explicit skip is `test_evaluation_comparison_integration.py:27`: it requires the separately approved localhost:15432 evaluation database. That coverage was not run against the guest database54012. The five existing expected failures concern first-visit contradiction, destroyed-item reappearance, unfulfilled-promise claims, capability rules and faction-allegiance extraction. Warnings retained: Starlette AnyIO alias deprecation, intentional HS512 rejection fixture key length,9existing Vue one-component-per-file warnings, PostCSS `from` option and large build chunk. Successful checks are not warning-free.

## Exact artifact and receipts

Final release: `vue-ba2b69b673827ad69c54ecc32cbd954daf990732ac5204ab3d0a14d56a1e8817`. The single final rail-label expression changed after the full Vue782 and21-stage matrix had passed on release `vue-e8ea645c14483e24e55a9c5bf65e2481ee60db19ec0def4aeec5283582060f72`. Those remain explicitly prior-snapshot evidence. The label change has43covering tests, changed-file lint/typecheck, a new strict build, and the repeated real-API4-group acceptance on the final artifact; the entire matrix/full Vue was not redundantly rerun.

| File | SHA256 |
|---|---|
| dist-vue/index.html | 69cd415ee6e0ae7ec62246ac41938965c9613d59b1c7aa5103baef125f5b308a |
| assets/index-6rWxoB6y.js | ccb7d7986039b74a8546ea984cade4739d6144bec628b3700e72c0447a9c4d9a |
| assets/index-BtEUDYQG.css | ea958841e5f7b09fb5067e02838fcb49694e03c4703cac9839bd7bf12ca2a289 |
| spec/api-openapi.json | bc5793a1d19df27541adaf645544f77828dfeb093fdbca0f6bfe40a8c332679f |
| /tmp/myink-guest-task4-matrix-final/receipt.json | 8d74a6c6c38b17a738d7fcbacd4b5283d36b3834b2baa2c1e6e0ec26bb04e934 |
| /tmp/myink-guest-task4-matrix-final/chromium/guest/receipt.json | 50d16916de025a0be021770daec7b6fe28518c1fde200080ba5157f13447ee90 |
| /tmp/myink-guest-task4-matrix-final/firefox/guest/receipt.json | d7422cc3daf818c785212bd06683bf4830e99c85dbd8f472b187357e4fd48240 |
| /tmp/myink-guest-task4-matrix-final/webkit/guest/receipt.json | 42da6c13d3bac34dc1cbe5e0314f59051b0aad87168316f98a634edb68b716f5 |
| /tmp/myink-guest-task4-real-final/receipt.json | 3ab659c8bbb51022eccd02f8e035212f99c3d33f5b660ee91111c11c6817b6bc |
| /tmp/myink-guest-task4-real-final/cleanup.json | 4b7da1f89c1f8e842bf0defc5c3a9fdbd3c71d0b6fdfe7610aee93cd8fc81fcb |
| /tmp/myink-guest-task4-real-rail-final/receipt.json | 53dd144dcc422cfacbab161a03de52a4d34fc2d67728cfe8c88124bce4082a21 |
| /tmp/myink-guest-task4-real-rail-final/cleanup.json | 4b7da1f89c1f8e842bf0defc5c3a9fdbd3c71d0b6fdfe7610aee93cd8fc81fcb |

Complete artifact/receipt manifests: `/tmp/myink-guest-task4-build-rail-final-manifest.json` and `/tmp/myink-guest-task4-receipt-rail-final-hashes.json`. Prior manifests/receipts are retained; the `real-final` paths above precede the label supplement and `real-rail-final` is current.

The real browser verifies separate guest IDs in clean contexts at the same synthetic IP, shared actual1short/7long remaining balances, isolated project lists, successful explicit restore-only POST with renewed expiry, invitation201 upgrade retaining ID/project, and old token/recovery401. Its proxy overwrites client IP and rejects writes outside guest authentication/registration. Quota reservations use the actual DB helper without a model worker. Final screenshots in `/tmp/myink-guest-task4-real-rail-final/` were inspected. The quota screenshot now shows the friendly “游客” label and fully visible “登出” inside the fixed rail at1280×720; the generated internal identifier is not displayed. Cleanup receipts and process inspection confirm fixture accounts removed and owned browser/proxy/API/test processes stopped. Dedicated service containers remain available for local testing. No interactive API or Vite server is currently running; ignored review/evidence files are retained because no commit has been authorized.

All engines cover desktop1440×960, mobile390×844 and390×600. Final Firefox/Chromium/WebKit short-mobile registration and mobile exhausted-upgrade screenshots were inspected: controls fit inside the scrolling dialog and registration stays reachable. Initial Firefox focus clipping was reproduced with unchanged geometry assertions and corrected in the shared NativeDialog. The earlier failed matrix is retained at `/tmp/myink-guest-task4-matrix`; it is superseded, not counted as acceptance. The synthetic exhaustion assertion was also corrected to require short-category exhaustion while long quota remains available. First full Vue781pass/1outdated-call-assertion failure and its6-test covering fix remain in the detailed report.

## Reproduction commands

Do not run database suites concurrently. Use an existing dedicated test environment and installed dependencies/browsers.

```bash
source /tmp/myink-guest-20261028/env.sh
/tmp/myink-main-admin-merge-venv/bin/python -m pytest tests/ -q -ra
/tmp/myink-main-admin-merge-venv/bin/python -m pytest tests/test_multiprocess.py::test_worker_kill_redelivers_checkpoint_without_duplicate_persist -q -ra
npm --prefix web run lint
npm --prefix web run test:shared -- --maxWorkers=1
npm --prefix web run test:vue -- --maxWorkers=1 --testTimeout=30000
npm --prefix web run build
PLAYWRIGHT_BROWSERS_PATH=/tmp/myink-vue3-browsers node --test web/scripts/merge-retained-assets.test.mjs web/scripts/default-frontend.test.mjs web/scripts/browser-cleanup.test.mjs web/scripts/browser-receipt.test.mjs
/tmp/myink-main-admin-merge-venv/bin/python scripts/test_verify_guest_browser.py -v
PLAYWRIGHT_BROWSERS_PATH=/tmp/myink-vue3-browsers node --test web/scripts/guest-real-browser.test.mjs
PLAYWRIGHT_BROWSERS_PATH=/tmp/myink-vue3-browsers npm --prefix web run test:browser:matrix -- --output /tmp/myink-guest-new-matrix
PLAYWRIGHT_BROWSERS_PATH=/tmp/myink-vue3-browsers /tmp/myink-main-admin-merge-venv/bin/python scripts/verify_guest_browser.py --output /tmp/myink-guest-new-real
```

The real verifier enforces test mode, disabled dotenv and nondefault loopback PostgreSQL. It starts its own API on a dynamic port and cleans only its own fixtures/processes. Its finite waits/deadlines and intentional missing-navigation test verify that a failed browser run produces a failed receipt and attempts browser/proxy/API/fixture cleanup.

## Local interactive testing

From the repository root, start the dedicated API:

```bash
source /tmp/myink-guest-20261028/env.sh
export SITE_ADDRESS=http://localhost
/tmp/myink-main-admin-merge-venv/bin/myink init --seed
/tmp/myink-main-admin-merge-venv/bin/python -m uvicorn myink.api.main:app --host 127.0.0.1 --port 28110
```

In another terminal, use this Vite process-only proxy override from the repository root. The equivalent ephemeral-port startup was verified; no repository config edit is required.

```bash
node --input-type=module <<'JS'
import {createServer,loadConfigFromFile} from './web/node_modules/vite/dist/node/index.js'
const {config}=await loadConfigFromFile({command:'serve',mode:'development'},'web/vite.vue.config.ts')
config.server={...config.server,host:'127.0.0.1',port:5174,proxy:{'/api':{target:'http://127.0.0.1:28110',changeOrigin:true}}}
const server=await createServer({...config,configFile:false})
await server.listen()
server.printUrls()
JS
```

Open the printed URL and choose “游客体验”. Stop both terminal processes afterward. These commands use test services; do not substitute production endpoints.

## Boundaries

Actual model generation, production Caddy/TLS and image deployment were not exercised. Real API auth/quota/upgrade evidence and synthetic generation/error UI evidence are distinct. Cookie transport policy behind Caddy is covered by the final route/config regression tests, with production/public sites enforcing Secure and only configured loopback HTTP permitting local cookies.

IP HMAC bucket keys and guest recovery digests currently depend on a stable `JWT_SECRET`. Future secret rotation requires explicit credential/quota migration planning; lifetime continuity across rotation is not established by this change.

## Controller rulings

Concise durable record of the explicit `Ruling` entries in the [execution ledger](../../../.superpowers/sdd/2026-10-28-guest-mode/progress.md). These decisions preserve authorization and evidence boundaries; they do not grant publication permission.

| Ruling | Reason / boundary |
|---|---|
| Work directly in main; no new branch/worktree | Existing project branch responsibilities and user authorization; changes stay reviewable in the working tree. |
| No task commits, pushes or deployments | Feature execution did not authorize publishing; review uncommitted diffs. |
| Execute the already-approved design without another plan approval | User explicitly authorized beginning; implementation is reversible and within scope. |
| Preserve ordinary registration with a permanent bearer; only guest identities upgrade in place | Avoid an existing registration regression while retaining guest account continuity. |
| Allow static scoped review during dedicated PostgreSQL recovery | Final acceptance still needs real tests; infrastructure-blocked checks are never reported passed. |
| Start independent frontend work while restoring the dedicated database | Avoid idle work, retain one implementer per shared interface and no concurrent database suites. |
| Consolidate final frontend lint/full tests/build/three-engine checks into Task4 | Avoid duplicate expensive verification; all gates remain mandatory on frozen source. |
| Overlap read-only frozen-source review with long verification | Completion still requires both outcomes; subsequent harness deltas receive review. |
| Prepare final cookie/OpenAPI/dialog fixes in ignored scratch while the main backend suite runs | Preserve the running snapshot; distinguish the pre-fix aggregate from post-fix covering tests. |
| Leave production rollout/live TLS, paid models, fingerprinting and unrelated rate-limit/admin/Pi/warning work outside scope | Respect approved design and authorization; no speculative expansion. |
| Keep JWT_SECRET stable; plan explicit credential/IP-ledger migration before future rotation | Current recovery/IP HMAC keys do not promise lifetime continuity across secret rotation. |
| Extend the current final wave with the guest-friendly rail label | The real browser exposed an internal generated identifier pushing logout out; keep the fix to label-only source/test changes and verify a rebuilt real browser, retaining prior full-suite snapshot boundaries. |
| Retain ignored review workspace until an authorized commit | No Git commit yet preserves that review evidence; leave the temporary evidence on disk. |
