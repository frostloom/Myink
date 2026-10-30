# Account and membership page refinement

User requests a structural account-page redesign and this ordinary-account message: “如果需要更快的写作速度、更高的写作质量，请联系管理员进行 VIP 升级。”

Use frontend-design with the established paper/night/contrast tokens, system UI font, one green accent and functional separators. Replace the asymmetric cards and oversized help banner with two coherent areas: an account/membership overview and a login-security panel. Identity occupies the narrower side of the overview; membership copy and two benefit descriptions occupy the wider side. Password form has current password on one row and new/confirmation fields side by side, stacking on mobile. Password-help text becomes a compact footer. No fake contact button or invented administrator contact address.

- [x] Tests first for ordinary upgrade contact copy and VIP already-active state, preserving role/member separation and guest/MFA behavior.
- [x] Change account template/styles without changing password, MFA, session ownership or unsaved-form logic.
- [x] Relevant tests, complete frontend lint/test/build; desktop/mobile/night screenshots; independent review.
- [x] Build and deploy frontend only at localhost, preserve running backend/data and existing assets, verify live release and ordinary-account page. No commit/push/merge/remote deployment.

Verification: 207 shared and 808 Vue tests passed (1015 total); lint has zero errors and nine existing warnings; typecheck and production build passed. Independent account review found no blockers. Desktop, mobile and night layouts inspected; deployed ordinary-account page shows the exact prompt, three password fields and no horizontal overflow at 390px.

Local frontend image: `myink-caddy:account-ui-b6f38a88-dirty-99b108808260`. Controller: `.local/account-membership-20261028/compose.sh`. Release and readiness verified, API/Worker container IDs unchanged, two previous frontend assets preserved byte for byte. Receipts and screenshots are in that ignored local directory.
