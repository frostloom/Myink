# Writing resource coverage and quality

User asked to publish the approved personal-page refinement first, then verify that genres/rules/styles are used, find suitable GitHub guidance and integrate appropriate choices. User explicitly chose natural expression and narrative momentum together, adjusted to genre.

## Plan

1. Publish frontend-only commit a8a4361e and record the release, unchanged backend IDs, retained assets and public browser check.
2. Audit frozen project resources and provider messages across long/short planning, writing, review and revision. Record the distinction between injected guidance, model tool reads and demonstrated literary quality.
3. Fix the reproduced long-form private-style gap in audit and patch prompts. Tests first; preserve author facts, output protocols, token budgets, model roles and resource overrides.
4. Add three small, editable resources through the existing versioned seed/catalog: scene causality, character dialogue and genre-dependent pacing. Adapt concepts in original Chinese wording from pinned MIT GitHub sources; do not import upstream agent orchestration, execute their Skills, or duplicate the existing humanizer/genre corpus. New catalog items do not overwrite existing published revisions or silently reselect resources in existing books.
5. Add three original, author-neutral style profiles: natural narration, brisk narration and nuanced character narration. No fixed POV, named-author mimicry, mandatory sentence lengths, fixed twist counts or sample plot facts. Authors choose a profile; existing private profiles take priority.
6. Validate new-resource publication, explicit selection/empty selection, long/short provider-message coverage, role scopes, genre and personal-style priority, immutable revisions, context budgets and preset availability. Run related tests and complete isolated Python regression. Record exact limits of any quality evaluation; do not claim prompt tests prove better prose.

Further audit findings (short-outline review failures silently treated as pass, optional-reference zero-read observability and post-revision short-form re-review) are recorded in the research report for a subsequent bounded change; they are not required to integrate this resource bundle.

## Verification

- Private-style regression: 10 failed / 1 passed before the fix, then 11 passed. New catalog/message/profile tests: 10 failed before adding the resources, then all passed including SQLite publication/snapshot/opt-out coverage.
- Related isolated integration set: 167 passed. Post-review style-library/runtime/private-style set: 99 passed. Independent reviewer: 38 pure tests passed, no remaining code blockers; clarified pacing text to preserve existing chapter-ending requirements.
- Final whole Python suite on dedicated myink-test PostgreSQL/Redis/RabbitMQ: 2212 passed, 1 skipped, 5 xfailed, 2 subtests passed (292.71 seconds). The skip requires a separate approved evaluation database identity; five xfails are existing conflict samples. First whole run exposed an old four-style list slice; test now explicitly checks all seven builtin IDs, readonly metadata and the private item order.
- Syntax and unchanged 119-path API contract checks passed. Frontend publication a8a4361e was separately verified with 1016 frontend tests, lint/build, production release, retained assets, unchanged backend and public browser.
- Rules/prompt boundaries were exercised with synthetic provider capture; no paid-model blind evaluation was run, so no measured literary-quality or AI-detection improvement is claimed.
- Release script review replaced the general initializer with a targeted, single-transaction publisher for precisely the six required IDs. Preflight checks candidate IDs; postflight additions must match the prior missing set exactly. Existing publications and book-selection hashes must remain unchanged; database backup/restore-list and both new Worker heartbeats are checked.

## Publication

Source d25d82752d4821ae701f3ed7ebbffea01b4b63f7 pushed and deployed https://myink.cloud for API and both Workers. Caddy stays at a8a4361e. The six resources published at version 1; original 134 resource records and book-selection hashes unchanged, counts remain 9 accounts / 20 projects / 60 chapters. Native amd64 no-network image smoke passed. Production readiness and both new Worker heartbeats passed. See `docs/evaluations/2026-10-29-writing-quality-release.md` for receipts and recovery boundaries.
