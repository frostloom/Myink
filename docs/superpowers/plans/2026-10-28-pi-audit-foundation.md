# Pi Audit Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user explicitly chose continuous inline execution without stage questions; one fresh final reviewer, no per-task implementer agents.

**Goal:** Append-only, redacted Pi audit outputs and a main-ready read-only consumer, with actual historical-owner002 export and durable capability/memory inventory.
**Architecture:** Dedicated SQLite audit schema → immutable hashed JSON pages + atomic manifest → pure main reader. Existing execution, fee and manager ledgers remain authoritative and unchanged.
**Tech Stack:** Python3.12 standard library/SQLite; existing pytest.
**Spec:** docs/superpowers/specs/2026-10-28-pi-online-closed-loop-design.md

## Global Constraints
- Originalserver manager/fee, cumulative50000000microyuan,9oldunknown/18115200hold. Audit cannot create a fee scope or serve as an execution approval.
- No mainmerge, admin-page/auth changes, real model calls, emails or business deployments in this foundation plan.
- Originalreal-provider fixed-input18case provenance stays distinct from onlinebusiness evidence; unknownoccurred_at/counters stayunknown.
- All newoutputpaths private/exclusive; preserve oldfailure/session evidence. Snapshotpages≤100events/1MiB, readerpaginationdefault25/max100.
- Later collector/reviewer/release wiring and actual nextday execution remain in the root goal, not completed by this subplan.

## Review Focus
- Duplicate key/partial write/export crash must not rewrite events or last good manifest.
- Secret-like nested/untrusted summaries, bool counters,NaN and unknownfields must not escape strictprojection.
- Hash/path/page substitutions, symlink/hardlink/traversal must not read outside designatedexport root.
- UTC+8 boundary, unknownhistoricaltimes, no-release vsunknownrelease and plannedtest vsactualresult must remain distinct.
- Auditreaders must import no execution/billing capability; originalcanonicalrows/costs must not change from retrospective export.

### Task 1: Dedicated immutable event store
**Files:** Create ops/pi/audit.py; Test ops/pi/tests/test_audit.py.
**Interfaces:** AuditStore(path,clock=None).append(record_key,record)->event; .events(run_id=None,day=None)->list; pure validate_record/sanitize projection.
Consumes trustedhost structured records with exactly kind,status,run_id,occurred_at,summary,details,version,changes,evidence,followups,mode,evidence_domain.
Produces v1envelope with authority=audit_only,sequence/chain/eventdigest,recorded_at/day/time_basis and redaction/truncation flags.
- [ ] RED tests: append/reopen/chain invariants; exact idempotence/conflict; UPDATE/DELETE denied; concurrentappend; audit schema rejected as feeLedger; field/size/secret/time/type rejection.
- [ ] Minimal strict record projection and dedicatedSQLite transaction append, close connections explicitly.
- [ ] GREEN relatedtests; inspect allresults; commit only this feature files.
Expected: source/fee no reads or writes, secret values absent from serialized event, all timestamps explicit.

### Task 2: Atomic export and main-only reader
**Files:** Modify ops/pi/audit.py; Create src/myink/pi_audit.py; Test ops/pi/tests/test_audit_reader.py.
**Interfaces:** AuditStore.export(root)->manifest; main AuditReader(root).runs(limit=25,offset=0,day=None), .events(run_id,limit=25,offset=0,kind=None), .daily(day), .enhancements().
Produces immutablepages/<sha>.json and manifest.json with schema/index/count/hash/watermark; run/event results use items,total,limit,offset.
- [ ] RED writer→main roundtrip, pagination, pagecaps, malformed/unknownschema/duplicateJSON/missingpage/hash mismatch, forgedindex/pathlink, crashmanifest retention.
- [ ] Implement pages/hash manifest publishlast and read-only validated paging without ops/Pi/model imports.
- [ ] GREEN tests and nooutside-file-read probes; commit.
Expected: oldgoodexports survive interruptedpublish, invalid data fails rather than empty/success.

### Task 3: Daily versions, next tests and enhancement inventory
**Files:** Modify both modules; Test ops/pi/tests/test_audit_daily.py; Create docs/contracts/pi-audit-v1.md, docs/pi/agent-enhancements.md.
**Interfaces:** export dayrecords from explicit eventfacts; followup embedded records remainplanned; actualtests distinctevents with stabletest_id; inventory keys come from actual toolschema/phase profiles and currentdeployed artifacts.
- [ ] RED UTC+8 midnight, no_release/unknown/passeddeployment distinction, sameSHAredep identity, unknowntime/zero/null, repeatedcandidate changes notdoublecounted, dueplan never countedpassed, simulatedrelease cannotclaimonline.
- [ ] Implement deterministicdaily summary and consumer methods; write exact JSONcontract/examples and source-backed rawPi capability/hostboundary/memory/dailyversion matrix.
- [ ] GREEN allfoundationtests and meaningful contract compatibility; commit.
Expected: main can display checkedresults/analysis/toolflow/failure/recovery/nextdayplannedtests/versionranges as data, without invokingPi.

### Task 4: Actual immutable historical export and final delivery
**Files:** Create ops/pi/audit_import.py; Test ops/pi/tests/test_audit_import.py; Create docs/evaluations/pi-audit-foundation-2026-10-28.{md,json}.
**Interfaces:** import_manager_run(state,billing,task_id,job_root,audit_path,clock=None)->receipt; export via Task2. Only read actualmanager/fee/job/session/tool/checker artifacts with fixedknownschemas/paths; nohostimport/execute ofcandidate/gold.
- [ ] RED copiedsyntheticvalidfixture→honestflow; hash/stale/badmode/unverified/unknownreceipt rejection; redaction; repeatimport no duplicate; oldledgers unchanged; missinghistoricaltime staysunknown.
- [ ] Implement mechanical projection of owner002 actual1selection/12development/14tools/18tests/147273.872ms/56758cost/9historicalholds and sourceversions; no fabricatedrelease or nextdaytestsuccess.
- [ ] Deploy a new fixed audit-only runtime/oneshot to produce private serverexports; originalfee/manager snapshots beforeafter exact. Download only redactedexports and read with mainreader locally. Existingmanager continues unchanged.
- [ ] FullPi regression + relevant reader/product packaging checks, one fresh finalreview of this plan's concrete diff, one authorRED/GREEN fixpass for important findings, no rereview. Preserve allnotes/evidence.
- [ ] Publish sanitizedresults and Pi branch commits/exactfourCI. Mark only this foundation subplan complete; continue rootgoal with realonlinecollector/automaticreview/release/recovery/nextday wiring.
Expected: actualmain-ready data exists and no additionalpaidcalls/budgetscope/reset/productrelease occurs.

## Plan self-review
Task1envelope is consumedunchanged by Task2; Task2dayindex contracts are extended only through Task3strictfields; Task4imports canonicalfacts into Task1/Task2, never treats audit as approval. Useroptedoutquestion/approvalgates; implementationchoices are authorcalls. The fullrootgoal remains unfulfilled until realclosedloop/crossdaygates are proven.
