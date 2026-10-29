# Personal page visual refinement

Use the established paper, night and contrast tokens and system UI typography. The account page approved in this conversation is the visual reference. This is a presentation update to existing Vue pages, with one useful empty-state entry into the existing style extraction flow. Keep all authentication, guest upgrade, model permissions, partial saves, draft guards and style persistence behavior.

1. Advanced settings: give EnvironmentPage its own CSS module, constrain the reading width, align role names, model selectors, source status and compact reset actions. Use consistent section heads and save footers for models, budgets and rankings. Keep advanced controls initially collapsed and retain accessible field/action names.
2. Account entry: replace the oversized anonymous registration prompt with a compact identity panel and balanced register/login actions. Style the guest upgrade form in the same panel. Refine the standalone login/register form with clear title, field rhythm and registration guidance; preserve MFA and submit behavior.
3. Style library: one bordered catalog/detail workspace with a single top-level new action, readable selection and profile content. Make empty states explain the next action and open the existing sample form. Show the action bar only when there is an action or feedback.
4. Verify relevant existing interaction tests and a new empty-state-to-extraction regression, then full frontend lint/test/build. Inspect actual desktop/mobile/night pages and style empty/new/detail states using an isolated browser session. Independent read-only review. Update localhost frontend only for review; preserve backend/data. Do not automatically publish these new visual changes to production.

## Verification

- New empty-state regression failed before the CTA was added, then passed. Relevant six-file set: 85 passed.
- Final shared tests: 207 passed; final Vue tests: 809 passed with `--maxWorkers=2` (1016 total). The first full run had one existing MFA test exceed its 5s timeout; its isolated 14-test file and both reduced-concurrency full runs passed without changing test logic or timeouts.
- Final lint: zero errors, nine existing warnings. Strict typecheck and production build passed; existing bundle-size warning retained.
- Independent read-only review found no blockers in authentication/guest/MFA/draft guards, separate preference saves/resets, field labels or empty-state behavior. Reviewer test execution was sandbox-blocked and is not counted as passed; the full test results above were run by the main agent.
- Real browser checked desktop and 390px mobile settings, login/register, anonymous account entry, guest upgrade, and empty/new/populated style-library states with local synthetic APIs. Night-theme settings and style detail inspected. No horizontal overflow in mobile checks; no real account, provider or saved model preference modified.
- Local frontend image: `myink-caddy:personal-ui-ff96adc7-dirty-c495f6dcd7e5`. Receipts and screenshots: `.local/personal-pages-20261029/`.
- Local deployment passed release and readiness checks, preserved both prior entry assets byte for byte and kept API/Worker container IDs unchanged. Runtime controller: `.local/personal-pages-20261029/compose.sh`. No commit, push or production deployment for this refinement.
