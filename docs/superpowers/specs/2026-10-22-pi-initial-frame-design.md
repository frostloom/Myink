# Pi bounded initial container frame

Real retained025 reports are about300KB, making the full first-pair worker inputs about355KB; current shared196608-byte frame cap rejects them before admission. Preserve the full report, views and frozen identity instead of trimming data or changing prompts.

Introduce INITIAL_FRAME_LIMIT=524288 bytes including terminating newline for the one host-to-worker initial message. Validate it at launcher preflight, exchange before initial write, worker initial readline and prepare_initial. Continue using FRAME_LIMIT=196608 for every subsequent relay/reply/result; HTTP body65536, total output1048576, deadlines, budget, policy, contracts and no-tool boundaries stay unchanged. Serialize in the same ASCII JSON encoding used for transport. Reject oversize before any partial initial write.

Use synthetic metadata to reproduce the large retained-report size without public prose. Verify complete report preservation and request identity, exact initial bound, oversize/tampered worker inputs, unchanged downstream limits and actual Linux two-slot MockTransport execution on the new closed source. Then complete the real-input non-live check against original state and refreshed official evidence. Never execute a paid request or enable the canonical policy in this task. No main merge or deployment.
