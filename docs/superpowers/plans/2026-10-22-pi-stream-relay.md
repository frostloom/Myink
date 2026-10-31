# Pi bounded SSE relay implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Execute inline; user has already asked to continue without questions and authorized commits/pushes.

**Goal:** Deliver valid SSE above 64 KiB without buffering the full HTTP response, preserving conservative settlement and bounded isolation.
**Architecture:** Host emits response_start, base64 response_chunk, response_end frames; worker validates sequence/count/bytes and writes HTTP incrementally with Connection: close. Legacy bounded status/body replies remain for existing synthetic probes. A ReplyStream owns lazy iteration and closure; exchange closes it even on timeout or broken pipe.
**Tech Stack:** Python stdlib, existing HTTPX, existing Linux Pi/Node. No dependencies.
**Spec:** This document includes the design; choices below are implementer decisions under the user's no-questions authorization.

## Global Constraints

- New explicit SSE wire budget: 1 MiB per HTTP 200, max 1024 chunks; each decoded chunk <=16384 bytes. Non-200 total and legacy body remain <=65536 bytes. The new aggregate bound is distinct from the existing text/session/result constraints; it is not unlimited response admission.
- Frame <=196608 bytes; trusted initial <=524288; container stdout <=1048576; requests <=4. Existing session bytes <=65536 and result verification remain unchanged.
- Strict incremental UTF-8 check across chunk boundaries; no decode/reencode of SSE bytes; end frame required with matching totals. Invalid/truncated/duplicate/out-of-order/oversized frames fail closed.
- Host validates actual bytes and deadline; worker independently validates incoming frames. After HTTP headers, failure closes connection without appending a second HTTP error response. End marker denotes transport completion only, not valid model usage.
- Keep canonical ledger/global policy/credentials unchanged; 0 paid calls; no retries or unknown release. Synthetic valid full usage may already be settled even if later transport/contract fails; do not invent unknown refunds or relabel known usage.
- Preserve primary failure_detail and cleanup behavior from 48b968e. response_bytes now saturates at applicable total limit+1.

## Review Focus

- Reader stops or breaks the pipe: source context must close without buffering unread data.
- UTF-8 code point spans chunks or ends mid-codepoint: preserve valid bytes and reject invalid completion.
- Missing end/sequence mismatch/empty chunk: never accept as complete transport.
- Many tiny chunks or excessive aggregate bytes: finite byte and frame budgets on both sides.
- Partial SSE with final model usage absent: durable unknown and second slot NOT_RUN; complete known usage is never retroactively refunded.

### Task 1: Protocol and stdio streaming

**Files:** Create ops/pi/relay_stream.py and ops/pi/tests/test_relay_stream.py; modify ops/pi/container_runtime.py.
**Interfaces:** ReplyStream(frames), close(); response_frames(status,chunks,remaining,progress) yields dicts; receive_response(readline,start,write) validates bounded legacy/stream responses and invokes callbacks with status/bytes.
- [x] Write tests for incremental delivery >64KiB, exact bytes, UTF8 splits, malformed/truncated frames, limits, finite chunks and close on failed exchange write. Run RED.
- [x] Implement shared protocol and exchange dispatch using finally closure. Run targeted GREEN.
- [x] Commit verified protocol deliverable.

### Task 2: Production host/worker integration and acceptance

**Files:** Modify ops/pi/analysis_launcher.py, ops/pi/lab/container_runtime_worker.py, ops/pi/tests/test_analysis_launcher.py; update evaluation and README.
**Interfaces:** route returns ReplyStream wrapping the HTTP context generator; worker receives via receive_response with bounded readline and incremental flush. Synthetic legacy route remains accepted.
- [x] Add gateway/ledger tests for >64KiB valid SSE DONE, >1MiB unknown stop, invalid UTF8 and cleanup combinations, update child test protocol reader. Run RED.
- [x] Wire host/worker; validate positive/negative scenarios, full Pi suite and compileall/diff-check.
- [x] Run fixed Linux real Pi with external HTTP mock: valid padded SSE >64KiB and overflow >1MiB; verify session/contract/settlement/cleanup and no paid calls.
- [x] Independent fresh code review, fix important findings with RED/GREEN; document actual limits and historical-cause uncertainty; commit/push Pi branch and update myink memory.

## Execution record

- Starting commit 48b968e; worktree clean on codex/pi-autonomy-design.
- Ruling: no brainstorming or plan-approval question — prior user explicitly opted out and authorized autonomous continuation.

- Protocol RED: 21 failed due missing module; first protocol/runtime GREEN: 63 passed.
- Integration RED: 7 failed / 71 passed (missing worker helper, old aggregate cap). Integration GREEN: 120 passed, 25.11s.
- Ruling: defer Task 1 commit until host/worker integration and full verification — same protocol must ship coherently; no intermediate failing test commit.
- Ruling: receive_response supports legacy replies only for existing bounded synthetic routes, without upgrading their admission or limits.

- Task 1: complete; protocol/runtime 63 passed; protocol and integration ship in one coherent final commit.
- Task 2: complete; targeted 120 passed, full 2095 passed/0 skipped/19 deselected; fixed Linux large and overflow accepted, independent review 0 Critical/Important.
- Review Minor: explicit known-usage-after-contract-failure assertion added (2 related passed); direct HTTP context close spy deferred, production with/finally and actual child broken-pipe closure test retained.
- Acceptance correction: original log display 88000 padding bytes was a typo; AST verifies actual 23*4000=92000. Original evidence retained with separate correction receipt.
