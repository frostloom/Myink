# Vue-only retirement and review — 2026-10-26

## Scope and authorization

User requested code-review, repairs, then removal of the React fallback so the maintained product is Vue only. Migration review baseline: `a96066c4...dd67ce5e`; retirement and fixes are local main working-tree changes over `dd67ce5e`. No push, deployment, branch/worktree deletion, production data mutation or paid model call is part of this round. The existing `.DS_Store` and `brief.pre-merge-local.md` were preserved; the latter still matches the saved original bytes.

The previous requirement to maintain two frontend implementations is superseded. Historical reports remain evidence of what happened then; current operations follow `docs/DEPLOY.md` and `web/README.md`.

## Standards review

Independent reviewer found and rechecked these issues:

1. LessonsPanel could display/restore another project's lessons after a project switch. Synchronous clearing and operation epochs now protect list results, errors and busy state.
2. ChapterPlanPanel could call the parent after unmount or associate an old confirmation with new task props. Operations capture task/chapter identity and invalidate on scope disposal/identity change; a new task also resets its plan draft.
3. Browser test SIGTERM/SIGINT cleanup could leave temporary profiles. Browser ownership now includes signal handling, an idempotent close path and removal of only its own profile/listeners; startup failure is covered too.
4. Concurrent checkpointer callers in the same process could create multiple pools. A process-local initialization lock now covers cache lookup through successful publication.
5. Workflow compilation could publish a chapter graph before the batch graph existed, including after failed compilation. Both are now compiled locally and published together under a process-local lock.

Each reported issue was checked against actual call paths; final independent review found no remaining actionable issue in these changes. No broad style refactor was requested.

## Spec review

Independent reviewer found and rechecked these issues:

1. An expired stream or replayed old terminal event plus a failed task snapshot could stop following an active task. Unknown status now keeps retrying with backoff.
2. A delayed forced refresh could overwrite newer SSE state and abort the live stream. Forced refresh now respects the status sequence, and callers receive the accepted current state.
3. Successful budget resume left submitted increments marked dirty. Successful requests clear the fields; failure keeps values and the idempotent retry operation.

Final independent review found no remaining actionable issue in the retirement changes. Vue-to-Vue release testing retains matching HTML/manifest checks, input preservation, confirmation/cancellation and in-flight write protection.

## Additional verification findings

- Cold isolated PostgreSQL with two worker processes exposed a real `checkpoint_migrations` catalog uniqueness race during setup. A session advisory lock `(728165, 1)` serializes schema setup on the same autocommit connection. A later real concurrent-index regression exposed a deadlock with blocking lock acquisition: its waiting SELECT retained a snapshot needed by the index owner. Nonblocking `pg_try_advisory_lock` polling with Python-side sleep now releases each failed statement before waiting; the actual concurrent-index regression failed with `DeadlockDetected` before this fix and passes afterwards. It is released in `finally`; initialization failures close the pool and do not cache a saver. Runtime checkpoint access still uses the health-checked pool. Cross-process blocking, failed setup/lock release/retry and thread initialization have regressions.
- The old `test_same_book_serial` assumed FIFO acquisition while bypassing the API inflight gate. It now waits until the first chapter holds the book lock and enters its provider before injecting chapter two, still testing concurrent contention. No production admission/order guard was relaxed.

## Vue-only implementation

- Removed 122 React-only source/test/entry/config files, direct React packages and fallback npm commands.
- Preserved framework-neutral API/draft/session services, types and the CSS used by Vue. Public URL contracts remain tested without importing the retired router.
- CI and local validation no longer build/run an alternate frontend. Caddy accepts only `FRONTEND_VARIANT=vue`; an explicit retired value fails with exit 64. Production bundle boundaries continue rejecting an accidentally introduced alternate runtime.
- Release manifests accept only Vue. The release browser test builds two different real Vue identities and tests both directions. Real-service browser scripts require only Vue output and retain reload/session/draft/theme checks.
- Historical hosted hashed assets remain compatibility data, with no selectable application entry. Existing stopped images/backups and already-running services were not deleted or replaced. `react-is` remains only as a dev transitive dependency of test serialization, not an application runtime.

## Verification evidence

Evidence is under `/tmp/myink-vue-only-*` and the temporary real-browser receipt directory. These are local operational artifacts, not committed credentials or production data.

| Check | Result |
| --- | --- |
| Frontend lint | Passed, 9 existing Vue warnings |
| Shared tests | 199 passed |
| Vue tests | 614 passed |
| Strict types / production build | Passed; existing large-chunk warning |
| Dependency audit | 0 vulnerabilities |
| Config / retained assets Node tests | 5 passed |
| Asset capture helper tests | 4 passed |
| Browser interruption / launch failure cleanup | 3 passed |
| Final Chromium / Firefox / WebKit matrix | 12/12 stages, 222 checks passed |
| Real isolated HTTP API | 19 checks passed |
| Real isolated Vue browser → API/PG | 12 checks passed |
| Concurrent cold-start worker + SSE + pool checks | 56 passed before the additional failure-path/thread tests |
| Final initialization regressions including real concurrent-index progress | 7 passed |
| Python compilation / evaluation catalog / OpenAPI diff | Passed; 20 audit cases, 40 catalog entries, 113 paths |
| Final full Python suite | 1971 passed, 1 skipped, 5 xfailed, 2 subtests passed; 2 warnings; 257.75s |
| Final Vue image build + isolated smoke | Passed, cleanup errors empty |
| Final API image build + isolated smoke | Final try-lock image build and smoke passed; 25 core versions match, 113 contract paths, healthz 200, cleanup errors empty |

Explicit non-passing attempts: initial browser matrix could not find default-cache browser binaries; using the documented `/tmp/myink-vue3-browsers` path resolved it. A test fixture initially used an overbroad string status type and failed strict typecheck; corrected to `TaskControlResponse`. First isolated backend run had 1 failure/52 passes due to the real checkpoint startup race above; the fix passed cold-start regression. One full Python run was deliberately interrupted (776 passed, 1 skipped, 5 xfailed at interruption) to include the subsequent thread fixes; it is not counted as a completed suite. Early standalone thread tests used an older editable-install source path; they were repeated against an exact `git archive dd67ce5e` baseline (3 expected failures) and explicit main `PYTHONPATH` (7 initialization checks passed).

A completed full Python attempt reported 8 failed, 1963 passed, 1 skipped and 5 xfailed. All eight failures were database connection failures in MFA tests while isolated PostgreSQL recovered from a backend process exiting with code 2 (10:42–10:43 UTC). PostgreSQL logs confirm recovery; the cause of the process exit is not established and is not attributed to the separate advisory-lock deadlock. MFA-only retry passed all 15 tests. The test stack was destroyed and recreated before the final serial full-suite run, removing possible invalid concurrent indexes and previous data. A final API rebuild first timed out fetching docker.io base metadata; the same public Python base via the previously used public.ecr.aws mirror succeeded; final image ID `sha256:f2014ecce70a7ec695bf7c9a21c142352107e23b168794f41655322fc1bed766`.

The fresh-stack attempt completed with 1969 passed and 2 failed: worker crash-redelivery exceeded its deadline, and an authentication rate-limit sequence returned 401 instead of 429 (consistent with its 60-second window expiring during suspension). The worker log jumps from 19:00:12 to 19:03:13; macOS `pmset` records Clamshell Sleep at 19:00:13 for 179 seconds, followed by another maintenance sleep. The unchanged multiprocess and rate-limit modules then passed all 20 tests in 84.66 seconds. Final full-suite retry uses `caffeinate -i` to prevent idle sleep (it does not override lid closure). No production code or assertions were changed for these two failures. The final API image's checkpointer and runner hashes independently match the workspace.

Final uninterrupted full suite completed successfully: **1971 passed, 1 skipped, 5 xfailed, 2 subtests passed** in 257.75 seconds (`/tmp/myink-vue-only-python-complete.log`). The skip is the evaluation comparison test requiring an explicitly approved fixed localhost:15432 identity; this task used isolated port 25432. The five existing expected failures are known L1 consistency feature gaps (first visit, destroyed items, unfulfilled promises, capability prerequisites, faction allegiance); they are not passing checks and were not expanded into unrelated feature work. Go code was unchanged and Go checks were not rerun. Final Standards and Spec re-review both report zero remaining actionable findings in this change scope.

## Limits

Review and tests establish no remaining actionable findings in the reviewed scope, not a mathematical absence of defects. Forced SIGKILL cannot execute in-process cleanup. Real paid-model generation, hardware input methods and long-term production observation were not repeated. The edited full-chain worker browser script received syntax review but its complete TLS/model-fixture scenario was not rerun; actual worker behavior is covered by the isolated Python regressions. Existing runtime services still use the earlier Vue deployment until a separately authorized release incorporates this round.

## Closeout

Owned isolated Compose services/network were removed with `down --volumes`; no owned test containers or pytest/worker child processes remained. Pre-existing local files remain unchanged. Hindsight myink policy and completion documents were stored and read back. Changes remain uncommitted in local main; no push or deployment was performed.
