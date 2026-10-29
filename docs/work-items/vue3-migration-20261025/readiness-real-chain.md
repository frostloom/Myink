# Replacement readiness: actual isolated runtime chain

Status: the final repaired backend and frozen Vue `index-LHE4QUm9.js` passed the gates below. All resources created for these tests have been removed. No production replacement, commit, push, merge or publication was performed. Pi was excluded.

## Final results

| Gate | Result | Durable evidence beside this report |
| --- | --- | --- |
| Complete final Python `tests/` | **1966 passed**, 1 skipped, 5 xfailed, 2 subtests, 2 warnings; exit 0, 192.34s | `readiness-final-python-tests.log` |
| Actual model HTTP → API → Rabbit → actual worker → DB | **13 checks passed** | `readiness-real-chain-api-receipt.json` |
| Actual MFA/admin/resources/multipart/password boundary | **10 checks passed** | `readiness-real-chain-security-receipt.json` |
| Final actual Caddy HTTP/local-CA TLS/live worker SSE/repaired replay | **4 checks passed**, exit 0 | `readiness-final-real-chain-edge-receipt.json`, `.log` |
| Final built Vue through actual TLS/API/worker | **11 checks passed**, exit 0, no page errors or HTTP 5xx | `readiness-final-real-chain-browser-receipt.json`, `.log`, `readiness-final-real-chain-admin-tls.png` |
| Model provenance | **255 AgentRun rows**: 143 `fixture-local` model rows, 112 zero-token internal rows; 143 actual HTTP requests, sole model `fixture-local` | `readiness-final-real-chain-provenance.json` |
| Scoped cleanup | All owned host processes, 5 containers and dedicated network removed; 8 ports closed; existing stacks preserved | `readiness-final-real-chain-cleanup.json` |

The early API13/security10 results precede the final replay-handler repair. The final complete Python suite, new-backend live SSE/replay and final Vue11 cover the repair and final runtime. They are not represented as a fresh repeat of the original 23 model/security scenarios.

The 1 skipped Python test is `test_evaluation_comparison_integration.py::test_direct_full_and_ablation_preserve_all_outputs_and_persisted_body`: its production safety guard in `myink/evaluation/isolation.py` hard-codes both DSNs to localhost **15432** before validating actual `pg_control_system()` identity. This dedicated PostgreSQL **28432** cannot satisfy that guard. No identity/guard was forged and no fixed-port stack was used. It remains **not passed**.

The 5 xfails are existing `tests/test_conflict_sample_suite.py` samples 5–9: first-visit history, destroyed-item reappearance, unfulfilled foreshadow, ability prerequisite, and faction affiliation detectors not implemented in the baseline. They are expected failures, **not passed**. Warnings are the third-party AnyIO alias deprecation and intentionally adversarial HS512 token test key-length warning.

## Exact final browser and backend identity

Final browser artifact/snapshots: `/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-vue-chain-browser-ya1fGO/`.

- Vue entry: `/assets/index-LHE4QUm9.js`.
- Index HTML SHA256: `cf8afe03dd7800c22a54bf0b5337c6e0bf781a010b8cea97334c60cba13825b0`. The receipt `builds.vue.sha256` is this **HTML** hash.
- Entry JavaScript SHA256: `8ace8616b0dc484c661be17834853f6a81fc1c95f4179f185173f46a2f12f51a`.
- Preserved React rollback entry: `/assets/index-BDxdzfd9.js`.
- Repaired `routes_sse.py` SHA256: `39587e77c3cb7334519f1e0957c2ba3d680e93f3336164ea62167a3afccb1454`.

The final 11 scenarios exercised ordinary TLS login; actual Rabbit manual-plan admission; active-task Vue→React→Vue same-origin sessionStorage draft/theme preservation without duplicate generate POST; native goal edit and persisted approved plan followed by actual worker stream-to-done; a truly dirty unique draft saved to DB; short creation/resource-first/manual start/reload recovery with exactly one generate POST and two confirmed chapters; real multipart feedback and authenticated blob attachment; actual admin password→enrolled TOTP login and three live chart SVGs; and Workspace/administrator rail logout with **exactly one actual POST per click**, HTTP200 awaited before further navigation.

Feedback uses the normal visible rail entry at 390x844, matching the original CSS mobile breakpoint, then returns to desktop for admin charts. No force click, internal UI event dispatch or API response mocking was used. Expected transient 404s reflect queue-to-task materialization; historical expired/cancelled event streams can return 410. Unexpected HTTP5xx blocks acceptance. Final page errors and HTTP5xx were both empty.

The earlier frozen `index-DdkQzNNW.js` also passed the complete prior 10-scenario run. Its receipt remains `readiness-real-chain-browser-receipt.json`; it does not substitute for the final LHE11 identity.

## Real SSE regression and repair verification

The fresh final-backend task `9c27a981-d8fc-469b-8b55-74602ef9017e` went through actual API→Rabbit→worker→local-model HTTP→DB and trusted local-CA TLS: **39 artifact deltas**, 52 observed frames, first delta precedes done by **1.50s**, no content encoding.

A real earlier worker task `41d8e6f7-dd07-484f-8c05-9ee4cb2a3c38` exposed a replay bug: its authentic 59 Redis frames end `node:persist` → `status:done` → `node:summarize`. The old handler skipped any terminal with any later row, incorrectly treating the summarize metrics tail as resumed work. The original failure is preserved in `readiness-real-chain-edge-replay-blocker.json`. The sole product implementer fixed terminal selection using subsequent authoritative statuses and added 17 boundary cases; related SSE/worker/events regression passed 95 tests before the final 1966-test suite.

The **new handler** was then tested via trusted TLS against that **unchanged original real-worker stream**, with no inserted Redis frames. From a midstream artifact cursor it returned **27 later frames including done**, excluded the cursor and reached EOF in **0.021s**. From the already-acknowledged done cursor it returned only the newer summarize node and reached EOF in **0.016s**, without replaying done. This is deterministic same-input repair verification: original frames come from the old actual worker, while the tested HTTP handler is the final repaired source API.

The observer polls AgentRun once per second and can stop before final metrics are copied, so requiring every new fast task to contain post-done summarize would be invalid. Two such harness attempts correctly failed their overstrong tail requirement; they were not counted as passing edge gates. An initial mistaken inference about every-five-chapter reflexion was corrected by reading summarize and observer code. No observer/Pi change was made.

## Isolation and model transport

Dedicated Compose project `myink-vue-chain-0025` used PostgreSQL/pgvector **28432**, Redis **28380** and a separate network/tmpfs database. Source API listened only on **28110**, actual worker consumed `queue:tasks-vue-chain-`, and local model HTTP fixture listened on **28120**. Core dependencies used a temporary Python3.12 environment constrained by `docker/constraints.txt`.

All external provider keys were explicitly empty. The sole model credential was the dummy `fixture-local-only`, model `fixture-local`, URL `http://fixture.invalid/v1`. Product SSRF guards intentionally reject literal private model URLs, so API/worker used a process-specific proxy to the loopback fixture, excluding localhost. `.invalid` is not public-resolvable. The fixture never forwards traffic, rejects other proxy POST targets and HTTPS CONNECT, and records only kind/model/stream/size metadata, never raw prompts or keys. No hosts file, production credentials or SSRF guard was changed. This exercises actual protocol serialization/HTTP streaming/queue/worker/persistence, not paid-model output quality.

Dedicated Caddy used HTTP **28080** and TLS **28443**, original routing/SSE/cache/security-header config and a dedicated host API upstream. Clients validated its exported internal CA; browser pinned only its temporary leaf certificate and disabled QUIC to avoid mapped-port alternate-service ambiguity. No OS trust-store change or public certificate issuance occurred.

Long-chain API13 covers setup/outline model HTTP, manual worker plan/confirmation, streaming, extract-created card review/reject/revise/resume, persisted content, rewrite/history and foreign-task denial. Short-chain covers chat/card/plan/review/commit, resource selection without auto-start, manual real short-write/review/revise and two confirmed chapters. Security10 covers MFA enrollment/confirmation/token revocation/wrong code/valid challenge, admin/ordinary permissions, invitation create/revoke, configuration masking, resource publish/select/adopt/stale409, multipart PNG exact bytes for owner/admin and foreign404, feedback resolution and password-change token revocation.

## Honest failure history and environment correction

Initial full Python evidence before the replay repair was **1949 passed, 1 skipped, 5 xfailed**, 297.63s; log remains `readiness-python-tests.log`.

After the backend repair, the first fresh-DB full run failed: **11 failed, 1934 passed, 21 errors, 1 skipped, 5 xfailed**, 250.07s. The harness changed DB/Redis but mistakenly retained runtime `PLATFORM_MODEL_*` during `myink init`, which imported its fixture platform model into the new test DB. Tests expecting no platform model saw `fixture-local` and platform quota429. This was test-environment contamination, not a replay assertion failure. The failed log remains `readiness-final-python-environment-failed.log`.

Only that isolated new test DB's single platform configuration row was removed. A separate canonical test environment explicitly cleared platform/provider credentials, proxies and fixture quota/budget overrides. All affected modules then passed **92 tests**, zero skip, exit0; `readiness-final-python-environment-targeted.log`. The subsequent full clean run is the final **1966 passed** gate above. No product/test assertion was changed to resolve the environment error.

The complete final suite used database `myink_vue_final_pytest`, Redis DB1 and the test `-mp-` queue, while the original actual-chain DB/Redis0 were preserved. Own API/worker stopped during the suite and restarted afterward with final code. API readiness200 **and actual AMQP consumer1** were rechecked before edge/browser tests.

Earlier browser harness errors (constant already-saved draft, hidden desktop feedback selector, wrong administrator logout label, navigation before logout completed) were corrected using actual UI/source evidence and independent tail checks. They are failed attempts, not passing gates. Actual product defects found by the browser—functional field native event fallthrough and duplicate rail logout invocation—were separately repaired and included in the final build before Vue11.

During Docker VM pressure the original dedicated Rabbit container became an unreapable zombie. Only its authorized scoped restart was attempted and failed; no daemon or existing stack restarted. A separate `--init` recovery broker on **29673** joined the dedicated network, and own API/worker gracefully switched to it. Actual AMQP channel/passive queue confirmed consumer1. The old zombie was ultimately removable during final bounded cleanup.

## Cleanup and remaining scope

Own host API/worker/model processes were gracefully terminated. Dedicated Caddy, recovery broker, PostgreSQL, Redis and original broker containers were removed, and the dedicated network removed, all exit0. No containers matching `myink-vue-chain-0025` remain. Ports **28110,28120,28080,28443,28432,28380,28673,29673** have no listeners. The original Myink stack, existing administrator-security test stack and unrelated containers still run. Cleanup evidence records names/statuses and contains no credentials. Receipts, logs and frozen build snapshots were retained.

Owned harnesses: `scripts/vue-real-model-fixture.py`, `scripts/vue-real-chain-api.py`, `scripts/vue-real-chain-security.py`, `scripts/vue-real-chain-edge.py`, `web/scripts/vue-real-chain-browser.mjs`. Standalone temporary diagnostic scripts were removed. No commit/push/merge/deploy was performed. Production DNS/public certificate issuance/deployment and paid-model writing quality remain outside these local replacement-readiness tests.
