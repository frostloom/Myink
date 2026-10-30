# Symmetric audit calibration — unreleased

The unchanged eight-unit input was audited twice independently in reverse order, three units per request,6HTTP total. Both passes see original requirements, context and draft; neither sees the other verdict. No runtime integration.

- S04/S08: both supported, positive controls preserved.
- S05: missing vs uncertain; hold.
- S06: violated vs supported despite an explicit inability to return on the original route; symmetric hold blocks a single-reader false approval.
- S07: both violated, consistent authoritative-password conflict, but copied source spans differ. Literal string equality cannot decide semantic agreement.
- S01/S02: the second batch copied BODY text into source_quote; whole batch invalid, hold. Their labels are not counted as semantic successes/failures for that batch.
- S03: originally labelled uncertain. Independent reread judged it likely genuinely violated because crossing is completed/stabilized before the instruction and pull. This fixture is stronger than merely narrated sequence. Preserve original input and expected label; treat as disputed/adjudicated, not evidence of common model misjudgment, and do not retrospectively count the old run as passing.

The interface correction binds authoritative requirement text to the program-owned unit ID, forbids model-supplied source text, and fills the complete original requirement in the result record after validation. Six protocol tests observed RED then GREEN. Only the formerly invalid S01/S02 batch is being re-run,1HTTP cap; other valid results remain frozen. This improves provenance/format, not semantic correctness. Repair agreement across different reasons still needs a validated contract; no automatic release approval follows.

Separate staged P05 run consumed32HTTP. A local candidate passed target checks, including both actors' route identity, but fresh full validation exhausted the cap. It therefore has no finalpass. The text in the failure log is an experimental working candidate; no author document or production database was changed. The prototype currently assigns its working draft after target pass, before complete final audit; any future runtime adapter must keep persistence behind complete finalpass.
