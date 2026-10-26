# Vue memory-form leave protection

`useMemoryFormGuard` evaluates owning reactive state, not DOM input events. Its small per-router scope set asks once for all nested forms, covers same-component route changes, removes scopes on disposal, and prevents navigation during shared API writes. Native `beforeunload` protects reload/tab close. Successful owning flows can permit only their intended navigation; failed saves retain dirty state. Anonymous-session recovery routing to `/login` from another page is exempt so expired-session recovery cannot be trapped.

| Owning form | Strategy |
| --- | --- |
| NewProjectPage | Brief/title/genres/style/count/word settings compared to defaults; conservative protection while generated setup or outline exists (includes restored server drafts), and during generation. Generated object/list edits are covered without input events. Internal created-draft query update and successful persisted workbench transition explicitly permitted; save-draft exit still confirms. |
| ShortCreationPage | Unsent/pending message, card compared to server card, style compared to server style. Successful commit navigation explicitly permitted; unsent text requires confirmation before committing. |
| EnvironmentPage | Full preference draft versus original server preferences; existing partial-save/reset merge preserves unrelated dirty leaves and failures. |
| LoginPage | Username/password/register/MFA input and MFA challenge; authenticated home transition explicitly permitted. |
| AccountPage | Password/MFA secrets and active enrollment while authenticated; cleared identity/session state removes protection. |
| SettingsPage | Target words versus loaded project; resource editor protected below. |
| Workspace GenerationPanel | Instruction and nondefault batch size. |
| Workspace ChapterPlanPanel | Editable plan draft versus current approved/generated plan, including nested/list changes. |
| Workspace TaskBudgetPanel | Nonzero budget increments and retained retry operation. |
| Workspace CandidatePanel | Nonempty modification reason. |
| ChapterEditor/useChapterDraft | Existing session backup remains. Dirty draft still protects native unload; backup failure registers in shared scope set for a single navigation prompt alongside nested forms. |
| AppearancePage | Existing theme token/wallpaper/preview dirty state and leave/update guards preserved. |
| StyleLibraryPage | Existing sample/edit draft and leave/update guards preserved. |
| FeedbackWidget | Existing unload/attachment protection preserved. Widget is app-owned and survives ordinary route changes, so no route prompt is added. |
| Admin PlatformConfiguration | Snapshot of model connections/routes, user defaults, prompts and genre overrides after initial load/successful save; click-created connections are covered. |
| Admin ModelManagement | Conservative protection while create/edit/delete-replacement editor is open. |
| Admin PlatformResources | Conservative protection while prompt/genre editor is open. |
| Admin WritingResources | Conservative protection while resource editor is open, including body controls, publishing/revision note and uploads. |
| AdminConsole invitations | Nondefault expiry/redemption values, label and custom code. |
| WritingResourcePicker (settings/workspace) | Selected resource input versus saved snapshot, including reorder/override bodies; conservative protection while private-resource editor is open. |
| ResourceUpdates | Open selection scope with selected pending revisions. |

StructuredTextField/AutoTextarea/GenrePackFields/ResourceBodyFields/RolePromptFields receive owning form values and are protected by their parent scopes. Read-only lore/audit/history/review pages, search/sort/filter/pagination/date-range view controls and disclosure state do not create mutation drafts. They do not receive discard prompts.

Limits: protection prompts before destruction; it does not persist these memory forms across a confirmed reload. Conservative generated/open-editor scopes can prompt even if their server-backed draft has not changed. Browser-native unload prompts depend on browser user-activation rules. Existing old clients need reopening to acquire this protection. In-page explicit editor cancel/reset/discard controls retain their existing semantics.
