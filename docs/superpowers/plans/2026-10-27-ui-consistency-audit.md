# Myink Round 4 UI source audit — 2026-10-27

Scope: read-only inspection of current dirty working tree; no edits to project, tests, build, browser interactions or screenshots. Existing changes were preserved. AGENTS.md and UI consistency spec read; no deeper web AGENTS found. Myink memory unavailable on localhost:8888 (connection refused). Findings below are source-confirmed defects, not claims of rendered verification. Other agents own rail persistence/catalog; parent owns fields/dialogs.

## Prioritized findings

1. **P2 — Theme dialogs leave keyboard focus/background interactive.** `web/vue/src/pages/AppearancePage.vue:290-309` only wires Escape. Preview and unsaved-exit rendered at bottom of file are `div role=dialog aria-modal=true`, with no showModal, entry focus, trap, background inert, or restore. Opening by keyboard leaves focus on the underlying tile; Tab can activate background controls. `SettingsPage.module.css:336-358` only supplies overlay/overflow. Use existing native AdminDialog or shared modal lifecycle preserving theme preview width; verify focus entry, Tab wrap, Escape and opener restore for both dialogs.
2. **P2 — Creation-resource footer ignores custom theme.** `web/vue/src/components/CreationResourcesDialog.vue:22` uses `background:var(--surface, #faf7ef)`. `--surface` is not defined anywhere in web/src or web/vue/src, so footer always light fallback while dialog is `--surface-1`. Use surface-1 and verify under dark custom tokens.
3. **P2 — Audit initial failure leaves permanent loading and no read-only retry.** `web/vue/src/pages/AuditPage.vue:16-30,86` catches list failure but reports stays null and template always displays loading for null. Only trigger-audit action remains, which unnecessarily performs a new audit to recover list. Add explicit loading/error branch and list retry; disable trigger until initial state settles if needed. Test rejected list then successful retry without trigger call.
4. **P2 — Lore reports false empty states while pending/failed, no initial retry.** `web/vue/src/pages/LorePage.vue:56-83,104-112`: Promise.all clears all data, but empty outline/characters/chapters/events/entities/foreshadows remain visible during request and failure; no retry for initial error. Add loading flag and success-only sections plus retry. One failed endpoint currently suppresses all successful response values; minimum fix separates failure from true empty presentation.
5. **P2 — Character-history failures cannot recover in-page.** `LorePage.vue:86-96`: failure assigns history[id]=[], historyError[id]; toggle immediately returns for any own history key, so collapsing/reopening never retries. Add explicit retry or allow error entries to reload, clear prior error on request; test fail/reopen/success.
6. **P2 — Short creation initialization failure has no retry or alert.** `web/vue/src/pages/ShortCreationPage.vue:137-151,390-402`: reload exists but no-data branch renders only error or loading text. After transient open failure all conversation controls are absent, so user must leave/re-enter. Add retry bound to reload and error alert/status distinction, prevent duplicate requests.
7. **P2 — MFA status failure gives a blank security section.** `web/vue/src/pages/AccountPage.vue:59-68` silently catches status failure, leaving mfaEnabled=null. Form at ~183 is hidden unless enrolling or status non-null. Add visible loading/error and retry for verified admins, without exposing enrollment until status known. Test rejected status + retry.
8. **P2/P3 — Settings load has no progress/recovery and editable placeholder value.** `web/vue/src/pages/SettingsPage.vue:23-36,66-68`: settings null pending/failure hides writing settings but target words remains editable at 3000; button disabled, no loading or retry. Add state-specific loading and retry; disable generation field until load succeeds so placeholder never masquerades as saved value. Test delayed/failing getSettings.
9. **P3 — Desktop control minimum conflicts with this spec.** `web/src/styles/global.css` .btn/.input/.textarea minimum remains 40px; only <=640 sets44. New spec says44px controls. Broad token change may need deliberate sizing regression; do not silently claim all controls meet44 on desktop.

No P0/P1 identified by source inspection. Absence of other findings is not browser certification.

## Exact route coverage matrix

Legend: S=source inspected; R=redirect reviewed. Every row still needs browser viewport/keyboard/long-content verification. Shared layout review includes RailLayout consumers, global theme form CSS, RouteBoundary, AdminPage scroll shell, AdminDialog native modal and overflow, admin LoadState/DetailPage/Pagination, and shared resource dialog/settings. Known nav-remount and StructuredTextField defects intentionally excluded above.

| Route | Source/state coverage | Outcome / follow-up |
|---|---|---|
| `/` | S App authentication/home dispatch | checking/unavailable retry/anonymous/admin redirect present |
| `/login` | S LoginPage and Login CSS | validation,error,busy,MFA-back present; normal login has no separate home/back affordance |
| `/projects` | R | redirects `/long` |
| `/appearance` | R | redirects `/theme` |
| `/long` | S ProjectsPage/form long/CSS | loading,error retry,empty,delete errors; rail persistence handled elsewhere |
| `/short` | S same ProjectsPage/form short | same states; no unique defect found |
| `/long/new` | S NewProjectPage relevant loading,error/step recovery,form/dialog render | draft recovery and creation retries available; long screen needs rendered checks |
| `/short/new` | S ShortCreationPage init,chat,card modal,resource dialog/CSS | finding6; card has focus/Escape lifecycle; footer finding2 |
| `/projects/new` | S alias to NewProjectPage | same legacy default form behavior |
| `/account` | S AccountPage/all template and status handlers | finding7; password errors,busy and role rail present |
| `/environment` | S EnvironmentPage load/update/template | load error retry,disabled forms,notices,dirty guard present |
| `/theme` | S AppearancePage state/dialog handlers and render + Settings CSS | finding1; previews use bounded overflow |
| `/styles` | S StyleLibraryPage loading,reload,editor/action bar and CSS | loading/error/empty; initial reload available; long editor is page-integrated, not modal |
| `/writing-resources` | S WritingResourceLibraryPage + UserResourceCatalog/CSS inspection | catalog classified/bounded; another agent owns full catalog behavior |
| `/projects/:projectId` | S WorkspacePage render/state headings + Workspace CSS | error,short-history retry,stage tabs,editor/chapter/right-pane responsive layout; no runtime verification of all task phases |
| `/projects/:projectId/settings` | S SettingsPage + ProjectWritingSettings | finding8; inner resources have own loading/retry/conflict handling |
| `/projects/:projectId/resources` | S ResourcesPage | loading/error retry/back/snapshot empty; redirects long books to settings |
| `/projects/:projectId/audit` | S entire AuditPage + CSS | finding3; details also lack pending indicator while fetching |
| `/projects/:projectId/lore` | S entire LorePage + CSS | findings4,5; graph component not deeply audited |
| `/admin` | S AdminPage/AdminConsole shared-load/table/detail flows | overview,analytics,users,projects,tasks,runs,logs,invites,feedback inventoried; shared states present; dedicated Analytics internals not deeply audited |
| `/admin/configuration` | R | redirects `/admin/models` |
| `/admin/models` | S PlatformConfiguration/model form/probes | loading/error/reload/save gate and disabled fields present |
| `/admin/model-routes` | S same component routes section | common loading/retry and return overview |
| `/admin/defaults` | S same component defaults section | common loading/retry and return overview |
| `/admin/prompts` | S WritingResources scope prompts | prompt-catalog loading/retry + native resource edit dialog |
| `/admin/genres` | S WritingResources scope genres | filters/cards/native resource dialog/history error state |
| `/admin/writing-resources` | S WritingResources all | list reload/empty/search and native editor; resource field parent owns |
| `/admin/projects/:projectId` | S ProjectDetailPage/View/shared shell | shared LoadState retry,chapters pagination,context refresh,return |
| `/admin/projects/:projectId/chapters/:chapterId` | S ChapterDetailPage/View/shared shell | shared LoadState,return project via backTo |
| `/admin/tasks/:taskId` | S TaskDetailPage/View/shared shell | task/runs LoadState,retry,pagination/readable snapshot,return |
| `/admin/runs/:runId` | S RunDetailPage/View/Dialog/shared shell | LoadState,refresh,missing-detail banners,return |
| `/admin/users/:userId` | S UserDetailPage/shared shell | LoadState,account detail/metrics,return |
| `/:pathMatch(.*)*` | R | redirects home; no dedicated not-found message |

## 初始审查边界（修复前记录）

This is route-level source coverage, not an exhaustive review of each descendant widget. Deep internals not reviewed: WorldGraph, all CanvasMedia theme variants, every chapter editor/task control, standalone Analytics charts, every administration CRUD dialog. Browser checks still needed for all routes, notably 390px/768px/desktop horizontal clipping, long dialog content/header/footer reachability, dark custom theme, delayed/error/empty requests, keyboard focus and back/scroll restoration. No test/build/service mutation performed.


## 本轮后续修复

上述1–8项已修复并增加回归。第9项按既有设计保留桌面40px/触屏44px，管理员导航改为44px；设计文档已同步。追加检查并修复GuestShell/VersionHistory/CandidatePanel的原生模态与焦点行为、默认按钮浏览器白底、管理员账号页导航去重。最终验证结果单独记录，避免把源码检查误作浏览器端测。
