# Admin VIP UI refinement

User approved directly implementing four navigation groups and a side-by-side normal/VIP model allocation page. Preserve the paper/night/contrast token system and existing API behavior. Continue on codex/vip-service without committing or merging. The existing local deployment is the review target.

- [x] Tests first: navigation groups and exactly one current destination; normal/VIP effective-model inheritance, eligible options, immutable updates and scheduling weights.
- [x] Group admin navigation into operations, membership, models/policies and writing resources; use consistent outline icons, a stronger current-page marker and a mobile menu.
- [x] Extract ModelRoutingBoard.vue: role rows, ordinary and VIP columns, explicit effective model/inheritance, separate scheduling panel with live share bar. Collapse service readiness and align save actions with page heading.
- [x] Give model/account membership badges a consistent, visibly different treatment. Keep member tier separate from administrator role.
- [x] Run relevant frontend tests, complete lint/test/build and inspect desktop/mobile plus night theme in a real browser. Check saving and inheritance without modifying live model policy.
- [x] Independent review; rebuild and deploy only the frontend locally using preserved runtime configuration, verify live release and screenshots. Record results.

Visual decisions: retain canvas #efeadd, panel #fbf8f1, editor #fffdf9, ink #3f3a36 and the existing green accent through tokens. System UI font remains; headings 28–32px, group labels 12px, row names 14px. Use one comparison table and functional separators instead of separate repeated form panels. VIP uses a filled membership label plus its own column surface; ordinary membership uses an outlined label. Inheritance is written next to the effective model, never implied by color alone.
