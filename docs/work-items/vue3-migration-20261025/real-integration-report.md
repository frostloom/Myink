# Vue real isolated integration verification

Status: all listed real-service checks reran and passed on the final Vue build `index-BWgRncmt.js`. The dedicated test services have been cleaned up. No production services/data, paid models, or project implementation files were changed by this verification worker.

## Isolated environment

- Dedicated Compose project `myink-vue-integration-2305`, independent network, tmpfs PostgreSQL with pgvector, Redis and RabbitMQ. Loopback host ports `25432`, `26380`, `25673`; fixed `myink-test` and running development/admin-test stacks were not used.
- Dedicated `/tmp/myink-vue-real-venv-2305`, Python 3.12.15; installed `.[dev]` constrained by repository `docker/constraints.txt`.
- Real source API on `127.0.0.1:28100`; application DB role `myink_app`, checked `rolsuper=false`, `rolbypassrls=false`; API report connection uses the independent DB's `myink_report` role.
- `APP_ENV=test`, `EMBED_ENABLED=0`, `RANKINGS_ENABLED=0`, `QUEUE_PREFIX=-vue-real-`; model API keys explicitly empty. No model provider was configured; no generation worker was launched. A direct DB count found **0 agent runs for all `vue_` browser fixture accounts**.
- Repository `myink init --seed` ran only against this independent database. One additional ready project/chapter was inserted as deterministic content fixture; all subsequent browser reads/saves went through the real API and database.
- Dedicated Caddy container `myink-vue-integration-2305-caddy`, loopback port `28101`. Original Caddy routing/cache/header config retained; only upstream `myink-api:8100` replaced by `host.docker.internal:28100` to reach the isolated host API. HTTP only; no certificate/TLS claims.

## Evidence

| Layer | Actual result | Evidence |
| --- | --- | --- |
| Real PostgreSQL/Redis Python regression | 6 files, **108 passed**, no skip; 1 third-party anyio deprecation warning | `/tmp/myink-vue-real-pytest-2305.log` |
| Real HTTP API | **19 checks passed** (18 HTTP behaviors plus 1 isolated DB fixture setup) | `real-api-receipt.json` |
| Real Vue browser → actual API/PostgreSQL | **12 checks passed**, 89 actual API responses, 0 HTTP 5xx, 0 browser page errors | `real-browser-receipt.json` |
| Real Caddy HTTP/cache/proxy | **5 checks passed** | `real-caddy-receipt.json` |

Python command (environment first loaded from the dedicated test env file):

```sh
/tmp/myink-vue-real-venv-2305/bin/python -m pytest tests/test_auth.py tests/test_environment_routes.py tests/test_chapter_versions.py tests/test_writing_resource_routes.py tests/test_writing_resources_integration.py tests/test_sse.py -q
```

The first Python attempt had 3 failures and 16 setup errors because this was initially an empty DB and the original fixtures require demo seed. No code was changed to hide them. After `myink init --seed`, the complete same six-file command passed 108/108. The API and browser seed accounts were then created separately.

API checks cover invitation registration, real password login and server session, anonymous denial, creation request-id idempotency, cross-account project lists and owner denial, environment leaf update/reset/account isolation, private-resource account isolation, resource snapshot selection and 409 revision conflict, resource updates, chapter read/save/409/history, logout token revocation. Script: `scripts/vue-real-integration-api.py`; requires explicit `MYINK_REAL_METADATA`, `MYINK_REAL_INVITATION`, `APP_ENV=test`, and dedicated DB port 25432 before any requests. Credentials exist only in temporary fixture metadata, not this report or receipts.

Browser checks cover Vue registration and empty new account, logout, actual login/account switch, workspace deep link and chapter list, saved content surviving reload, real version history, settings/resource snapshot, environment/style contracts, ordinary-user admin denial. The script uses a loopback server which transparently proxies **all** `/api/` requests to the real API; no endpoint responses are mocked. Outbound browser requests are blocked unless they are to this server's origin.

The browser also switches the static root **Vue → React → Vue at the same origin**, preserving both builds' hashed assets. In both directions it verifies the same authenticated username, an unsaved `sessionStorage` chapter draft, and a custom theme name in `localStorage`. This is a local rollback/storage-compatibility rehearsal, not production publishing. Source: `web/scripts/vue-real-integration.mjs`.

Initial browser fixture runs stopped at an incorrect exact-text selector for a resource row containing compound text. The selector was corrected to the real named “移除本书选择” button; no application change was made. Complete rerun passed.

Artifacts for this passing run:

- `/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-real-browser-pJdyle/receipt.json`
- `/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-real-browser-pJdyle/real-workspace-history.png`
- Vue entry `index-BWgRncmt.js`, index SHA-256 `c8de0ecfb6da106bd338b7447fd49a02a0a2c1eb0733eeaf4fdc29de51d6f63a`.
- React entry `index-BDxdzfd9.js`, index SHA-256 `fc8eff871b4366624c0b5b7507e68a63c8023a18a7dc3d015765b917c47964ae`.

## Re-run entry

With the isolated API and seeded invitation available (never use the production API or normal database):

```sh
source /tmp/myink-vue-real-env-2305.sh
MYINK_REAL_METADATA=/tmp/myink-vue-real-metadata-final2.json \
MYINK_REAL_INVITATION=vue-real-invite-2305 \
MYINK_REAL_API_RECEIPT=/tmp/myink-vue-real-api-receipt-final2.json \
/tmp/myink-vue-real-venv-2305/bin/python scripts/vue-real-integration-api.py

MYINK_REAL_METADATA=/tmp/myink-vue-real-metadata-final2.json \
PLAYWRIGHT_BROWSERS_PATH=/tmp/myink-vue3-browsers \
node web/scripts/vue-real-integration.mjs
```

The API script makes fresh account names per run. The browser script snapshots both build directories to its unique temporary output directory, so a concurrent build cannot invalidate the run's assets. The browser script expects the chapter state prepared by the API script; rerun that preparer before a repeated browser run.

## Explicit limits and cleanup

These results do not validate real model quality, full generation-worker scheduling through a production broker, production TLS/certificate issuance, external model endpoints, MFA hardware/authenticator UX, actual mobile IME devices, or long-duration video playback. The existing selected Python SSE/worker admission tests use real Redis/database plus controlled event/provider fixtures; that is separate from end-to-end model generation.

Final-build HTTP 19 + browser 12 + Caddy 5 checks reran successfully. This worker then stopped its dedicated API process (PID 49420), stopped its own Caddy container, and ran `docker compose -p myink-vue-integration-2305 -f /tmp/myink-vue-real-compose-2305.yml down --volumes`. Final absence/port checks are recorded below. Temporary receipt/build snapshots and the isolated venv are retained for review; existing development/admin-security-test stacks were left running. No deployment, commit, push, or merge was performed.

Cleanup verification: no matching dedicated containers or networks remain; all five dedicated ports refuse connections. All nine previously running Myink/development/admin-security-test containers are still running. Durable evidence: `real-cleanup-receipt.json`.
