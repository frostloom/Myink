# Vue 3 + TypeScript 阅读指南

从 `web/vue/src/pages/ProjectsPage.vue` 开始：`ref`保存列表和错误，`computed`派生长短篇与草稿列表，挂载时请求，卸载后忽略旧回包。模板负责显示状态，API继续复用原有类型化客户端。

| 阅读顺序 | 入口 | 要掌握的内容 |
| --- | --- | --- |
| 1 | ProjectsPage.vue、ProjectRail.vue | props、条件/列表渲染、事件、RouterLink、computed |
| 2 | EnvironmentPage.vue、SettingsPage.vue | 受控表单、watch、只提交修改字段、异步失败状态 |
| 3 | App.vue、authContext.ts、session.ts | provide/inject、只读状态、账号生命周期、卸载清理 |
| 4 | StructuredTextField.vue、GenrePackFields.vue | 泛型props、结构化值与可编辑原始文本的区别 |
| 5 | useChapterDraft.ts、ChapterEditor.vue | composable、响应式状态、保存快照、409冲突和导航保护 |
| 6 | useTaskEvents.ts、WorkspacePage.vue | SSE、watch数据源、重连游标、恢复任务与派生状态 |
| 7 | themeContext.ts、FeedbackWidget.vue、admin/ | 跨页状态、媒体资源清理、渲染函数、后台权限与版本并发 |

`.vue`中有两种原生Vue写法：`<script setup>`配模板，以及`defineComponent/setup`返回`h()`渲染函数。它们都使用Vue的响应式和生命周期；复杂页面先保留业务结构以便对照旧实现。学习新组件时优先用`<script setup lang="ts">`配模板，不必先模仿长渲染函数。

TS先理解`interface`、联合类型、`ref<T>`、函数参数和API返回值。不要用`any`绕过类型检查。先跑对应测试，再改一个可见行为；`npm run test:vue -- vue/src/pages/ProjectsPage.test.ts`是较小的起点。

迁移中最容易混淆的差异：Vue文本输入使用`@input/onInput`；组件内容通常通过slot；watch清理使用第三参数`onCleanup`；`h()`样式的长度需要显式`px`；多数据源watch应使用`watch([getterA,getterB],...)`避免返回新数组造成无意义重置。现有审查回归保留了这些真实错误的复现。
