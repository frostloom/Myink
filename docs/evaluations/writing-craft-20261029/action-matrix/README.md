# Actor/action research, full automation retained

User explicitly rejected mandatory author confirmation. This prototype is not wired into runtime. Do not count protocol unit tests or hand-authored question inventories as prose-quality acceptance.

- First matrix calibration: five clear source/body fixtures correct. The pre-labelled door/opposite-seat positive was independently judged ambiguous; the original positive label, modelnot_observed response and review remain archived. Do not relabel it into a pass.
- Next six fact-query controls all matched labels: atomic seating, unambiguous relative position, forbidden ending facts, return/incoming-route identity, original good clock readings, and the original missing-password/use/no-acquisition facts. The questions were supplied by the experimenter; this does not validate automatic discovery.
- Automatic inventory/repair v1 on four saved texts: P01finalfalse, P02modelpass, P05modelpass but original return-route gap still present (new patch only clarified single spell usage), P06protocolfailure. This is not a stable end-to-end result.
- Failures diagnosed: unspecified actions were strengthened into obligations on every character; a free-text own-route predicate lost the actual path-identity test; a genuine missing-permission quote from the previous paragraph was bound to the current paragraph, causing a false protocol failure.
- Parser now represents one_of groups separately from individually-required actions. A group fails as a group, so repair prompts must not require every alternative. Evidence is bound to the exact unique allowed source paragraph; source time anchors are never approximated.
- Source enum test4:3correct; named乙was not required to record but labelledforbidden despite a correct reason. Four independent boolean fields are now decoded in code. The first boolean test6:5correct; unassigned global obligation was not attributable to named actor slots. That original result remains. A new global-event subject plus explicit-alternative fixture tests the representational fix, not a changed prose outcome.
- Next automatic prototype must preserve decision/arrangement vs already-completed action, preserve the actual original natural-narration profile, bind the candidate selected writing resources for writer calls, and append original predecessor evidence to patch requests. Earlier plain prototype writer calls did not use this exact full candidate binding; do not overclaim their representativeness.

Current application-independent kernels remain experimental. No model route, queue, author book, frozen snapshot, production style row or deployment changed.

## Actual Anthropic thinking diagnosis

Both connections use Anthropic protocol. The earlier OpenAI-channel probe skipped both and made zero HTTP calls; the suspected OpenAI reasoning-as-final fallback is not on this active path. Raw Anthropic probe made4requests: disabled-thinking mode falsely accepted missing乙seating on both connections; explicit enabled/high mode rejected it on both. Disabled-thinking was not uniformly honored: one disabled request still contained a separate thinking block. Presence of a thinking block alone does not show high effort. No raw thinking text was logged.

Paired six-fixture comparison made24requests. Disabled mode:10/12correct, two false approvals (one per model on missing乙). Explicit high:10/12correct overall, zero false approvals among valid answers, but two invalid responses (one all-thinking6000-token exhaustion, one final JSON omittedstatus). Thus this does NOT establish an overall completion improvement or stability: both modes complete10/12correct. High thinking may address the semantic blind spot but introduces output and latency issues. Original fixture labels/results retained. See raw logs, protocol, and summary for usage. Counters include all attempts; incomplete outputs count as failures, never passes.

The guarded runtime now rejects finish_reason=length even if a syntactic JSON prefix parses or prose is nonempty. Four regression tests cover JSON recovery, incomplete prose rejection, default bounded exhaustion and artifact_failed→artifact_complete recovery; independent review found no concrete regression. This is output-integrity protection, not evidence of prose quality.

## Matrixv2 and epistemic review

Matrixv2 automatic four-case run:35HTTP attempts (P01 11,P02 7,P05 10,P06 7). P01 failed after requirements were over-assigned to all actors and a revision changed dialogue responsibility; P02 modelpass with useful seating/motive patch; P05 failed despite correcting own-route identity (negative question+forbidden double negation caused false rejection); P06 modelpass after unnecessary changes to valid dialogue. Not stable, no quality acceptance. Local unexecutedv3 at this point added literal subject/member bindings, scene-level unbound tasks, positive-question validation and preserved goal requirements.

Later independent original-text review disputes P01's original hard-negative label: the dialogue supplies possible evasiveness about responsibility, so password denial followed by use is a continuity ambiguity, not a certain author-world contradiction. Keep old label/run and this later disagreement; do not count it retroactively as a success. P06 independently judged sound. P07 is a new stronger negative with authoritative source and narration confirming no password or new authorization; inventing acquisition is forbidden.

Cumulative historical attempts317 + matrix/source research91 =408 before protocol probes. Actual raw Anthropic probe4 plus paired thinking comparison24 brings the completed total to436 before whole-text thinking and its separate inventory diagnostics. The OpenAI probe contributes0. Some usage fields from older provider error paths are absent and cannot be treated as zero billed cost.

## Whole-text thinking diagnosis results

All-high matrixv3:4HTTPrequests, all fail at source inventory, no repair ran and no finalpass. Raw same-inventory probes2requests: HTTP200 both; high10000 endedmax_tokens with incomplete text, medium8192 endedmax_tokens thinking-only. Single-case hybrid2requests: ordinary-mode inventory produced negative-predicate question, correction reply failed JSON parse before body reading. This run never tested body thinking, and no output was accepted. SSH disconnected after launch; retrieved log and read-only process/container check confirmed finished with no remaining worker-run container. No rerun was launched for the interrupted connection.

Cumulative completed attempts444 before the next8request direct existing-audit comparison (436+4+2+2). The all-high wrapper loses usage metadata when provider returns its legacy empty-content error, so zero in those usage rows does not mean zero billedtokens. Raw2request diagnostics preserve actual10000/8192output consumption. No deployed behavior or model config changes.

## Direct audit and low-effort calibration

Existing audit paired comparison8requests: P02currentvalidpass misses sharedseating; P02high also sayspass but schema invalid (empty replan_target), so not a semantic success. P05current sayspass with invalidschema, high exhausts8192allthinking. CorrectP06 validpass inboth. P07both find authoritativepasswordconflict but outputs invalidschema (currentinvalidseverity; highmissingconfidence), and current includes a prohibited new-authorization repair alternative. Detection alone not adequate repair. Broad high audit is not an accepted replacement. See full rawanswers; no output was treated as passed merely due to verdicttext.

Primary low-effort fidelity calibration6requests:6/6validcorrect, no truncation. Missing-person negative correctly rejected, positive preserved. Durations2.1–15.4s. Original gold/prompt/handclaims unchanged. This is a narrow positive result and NOT wholetextstability or prosequality. Cumulative completed458calls before the singlecase low matrix candidate (444+8+6).

## First complete stage-specific case

V6 P02 completed11HTTPrequests, patched3spans, automaticrecheckpass. Blind reviewer independently accepts revisedA and prefers its explicit daughter's seating; originalB seating is ambiguous, not a definite spatial contradiction. Original motive and sharedphoneviewing were already supported. Addedmotivephrase is optionalclarification; changingmother'sclicking is unnecessary. Do not claim all3model findings were correct or broad prose improved. This is one acceptable repaired/clarified sample with remaining over-literal false-positive behavior. Cumulative475before unchanged three-control run (464+11).

## Confirmed JSON corrective-turn defect

Anthropic conversion hoists system messages, leaving badassistant output last on JSONretry. A real converter regression test reproduced the assistant-ended payload; `_llm_checked` now sends JSON corrective requests as user turns (ordinarytext retry unchanged). Targeted33pure checks pass and independent code review found no concrete regression across Anthropic/OpenAI, streams, budget and tool boundaries. Full latest suite is running; the earlier2264run predates this fix.

Paired raw4requests on same actualfailedP06inventory and same correction: both existingmodels fail with oldsystemrole (one max_tokens plusBOScommentary, one repeats incompleteprovenanceJSON); both succeed with newuserrole and groundedsubjectquote. This supports the protocol rootcause, not general prose stability. V7sourcebinding enabled P05to reach later sources but normal correction still broke. V8changes only corrective role, same3case sources/limits/gates, now running.
