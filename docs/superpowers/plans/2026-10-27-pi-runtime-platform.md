# Architecture-bound Pi runtime implementation plan

> Use executing-plans inline, TDD and one fresh independent final review.

**Goal:** Unblock actualx86_64deployment without accepting mismatched runtime evidence.
**Architecture:** Shared strict Linux64 header/runtime machine helpers, optional native daemon binding, explicit host-derived frame-verifier pins.
**Tech Stack:** Python3.12stdlib, existingNode24.22/Pi1.1.0/Dockercontainment.
**Spec:** docs/superpowers/specs/2026-10-27-pi-runtime-platform-design.md

## Global constraints
- Original50CNYledger/735attempts/9unknown and originalmanager unchanged;0paidcalls.
- Productionmyink.cloud/current34b472cb containers untouched, noappmainmerge.
- Onlycanonicalaarch64/x86_64, defaultlegacyARM frame pin; unsupported/mismatched closed.
- Fullsourcefingerprints, native daemon binding, version/UID/network/session/tool/fee controls retained.

## Review focus
- ELFclass/endianness/header/type/ABI/machine cannot counterfeit accepted architecture.
- Validx86frame requires explicitx86pin; olddefaultstillARM and wrongpin rejects.
- Daemonaliases normalize narrowly; wrong/unknown nativearch stops beforecreate/modelcalls.
- Bothanalysis verdictpaths andallmodelhostlaunchers receivehost-derived pin, not worker claims.
- Historicalruntimeproofs stay immutable; nooffline test or syntheticprobe labeledproductionready.

### Task 1: Dual Linux64 platform binding and isolated acceptance

**Files:** newops/pi/runtime_platform.py; modifycontainer_runtime.py,analysis_trial_result.py,analysis_launcher.py,container_probe.py,development_launcher.py,selection_launcher.py; testsanddocs.
**Interface:** node_machine(path),canonical_machine(value),verify_runtime(runtime,expected_machine); verify_sourceprovenance.machine; ProbeHostexpected_machineoptional.

- [x] Write meaningfulsource/frame/daemon/launcher tests, valid-shapedELFfixtures; observeRED.
- [x] Minimalimplementation,focusedGREENandlegacyrelatedregression; nofinancial/prodmutation.
- [x] Freshindependentreview,authorfixpassifneeded; fullPi/Node/syntax/diff.
- [x] Newimmutablelocal/serverruntime snapshots and0model fixedprobes, auditresourceabsence/history/productionhealth; reportanynot_run honestly. Commit/pushPi branch/exactHEAD4CI, keepgo-livegoalactive.

Actual:52newcases45RED/7existingcontrols,52GREEN/349related/307independent/2958full19deselected/Node54. Bothplatformactual2SDKsessions+native-mismatchrejecteach,4ownedcontainersabsent,7prodidentities+readyunchanged;0realmodels/statechanges. Independentnofindings. Finalcommit/exactHEADCIreceipt recorded privately afterpush; goalnotcomplete.
