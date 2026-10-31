# Pi canonical state custody for server handoff

## Purpose and chosen implementation

The user explicitly authorized autonomous development through Pi go-live and private-source DeepSeek calls within the original cumulative50CNY ledger. Real-source Unicode18 acceptance is complete. Before that ledger moves to the actual x86 server, a copied SQLite database must not become a second independently spendable budget. Use Python3.12/SQLite append-only custody events in the existing billing ledger, checked atomically in the existing reserve transaction. This is a trusted-host control, not protection from a malicious root operator rewriting every artifact.

Retain local-trial-1 scope, all operations/events,739known+9uncertain attempts and their18.1152CNY holds,50CNY cumulative ceiling, closed schema4 policy, original manager history and old blocked/abandoned tasks. No daily reset or server_daily_enabled bypass. Code development and isolated synthetic handoff tests do not themselves migrate canonical state, transfer credentials, enable a service or deploy product code.

## Contract

- Legacy ledgers without custody events keep existing reservation behavior.
- A freeze names an explicit unique transfer ID, trusted authorization reference, current source binding and exactly one destination binding. Binding contains stable native-host identity SHA256 and canonical absolute ledger path; no model-supplied hostname/path. Native identity is Linux machine-id or macOS IOPlatformUUID, hashed and never exported raw. Unsupported/missing identity fails closed.
- Freeze and reservation serialize on the same SQLite transaction. Freeze refuses any pending model-attempt, including expired pending permits: settlement/reconciliation must precede transfer. Historical terminal uncertain holds remain. Freeze refuses wrong current owner and repeated transfer IDs; does not modify old rows or receipts.
- After freeze commits, every model reservation on the source or a copied frozen ledger is denied before analysis-slot mutation, budget allocation or transport. Totals and audit reads remain possible. Trusted operators quiesce controllers before creating consistent SQLite backups; custody blocks paid effects, not every diagnostic metadata write.
- Existing SQLite backup API captures WAL-consistent frozen billing and separately quiescent manager state. A canonical logical snapshot digest combines separately hashed complete operations and ordered events. Each freeze captures the immutable operations digest; chain reads recompute each transition input against the append-only event prefix, and activation refuses operations changed since freeze. This binds activation; file-byte hashes alone are insufficient because opening SQLite may change journals. Private originals/export/receipts are retained, never overwritten or removed.
- Activation must match latest frozen transfer ID, source logical snapshot digest and destination native-host/path binding. Append an immutable activation event only on that destination copy. Source remains frozen. Once active, reservations only succeed at the pinned host/path; copied activated databases at another location or host are denied. No implicit thaw/replay/new scope, no unknown release. Return migration requires a new explicit transfer.
- Validate full custody chain, exact schemas/field types, parent binding and alternating freeze/activation. Malformed/unknown custody events and duplicate JSON keys at any nesting reject rather than silently falling back to legacy mode. Duplicate/conflicting activation cannot create new authority; exact idempotence, if supported, must preserve history and current binding.
- CLI exposes status, freeze and activate with bounded fixed argument parsing, never shell/model commands. Status reveals hashes/state, not raw machine IDs or credentials. Freeze/activate require explicit operator authorization reference; no API call may infer authorization from model output.

## Verification and boundaries

RED/GREEN tests must cover legacy compatibility, frozen-source denial, wrong-host/path active copies, pending-reservation race, tampered/unknown/partial chain, target mismatch, stale snapshot, duplicate identity, cross-process reopen, preserved prefixes/unknown holds/cumulative limits and return handoff. Verify no denied reserve adds attempt or analysis metadata. Prove host identity parsing with fixed fixtures and real native-host observations, without printing raw IDs.

Use synthetic ledgers for actual local/server handoff acceptance;0 real model calls,0 canonical/credential/service/product mutations. One fresh final review of this feature, one author RED/GREEN correction pass if needed; no per-task reviewers. Dynamic Pi candidates remain excluded from host execution. Future canonical migration/service enablement needs separately concrete archived inputs and current runtime proofs.

## Explicit trust limits

This ledger alone cannot prevent restoration of an old complete ledger at the same host/path, cloned native machine IDs, or a malicious privileged operator constructing an entirely consistent alternate history. Those need an external anti-rollback authority and are outside this prerequisite. Do not claim physical-host uniqueness or protection from every historical backup. The concrete migration must archive old runnable inputs and keep one active operator-controlled custodian.
