import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'
import LoginPage from './pages/LoginPage.vue'
import ProjectsPage from './pages/ProjectsPage.vue'
import AccountPage from './pages/AccountPage.vue'
import EnvironmentPage from './pages/EnvironmentPage.vue'
import AppearancePage from './pages/AppearancePage.vue'
import StyleLibraryPage from './pages/StyleLibraryPage.vue'
import NewProjectPage from './pages/NewProjectPage.vue'
import ShortCreationPage from './pages/ShortCreationPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import ResourcesPage from './pages/ResourcesPage.vue'
import WritingResourceLibraryPage from './pages/WritingResourceLibraryPage.vue'
import LorePage from './pages/LorePage.vue'
import AuditPage from './pages/AuditPage.vue'
import AdminPage from './pages/AdminPage.vue'
import { AdminConsole } from './pages/admin/AdminConsole'
import PiConsolePage from './pages/admin/PiConsolePage.vue'
import PlatformConfiguration from './pages/admin/PlatformConfiguration'
import WritingResources from './pages/admin/WritingResources'
import { ChapterDetailPage, ProjectDetailPage } from './pages/admin/ProjectDetail'
import { TaskDetailPage } from './pages/admin/TaskDetail'
import { RunDetailPage } from './pages/admin/RunDetail'
import { UserDetailPage } from './pages/admin/UserDetail'
import WorkspacePage from './pages/WorkspacePage.vue'

export function createCandidateRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({ history, routes: [
    // App resolves the home only after authentication verification has finished.
    { path: '/', component: { template: '<div class="empty">正在打开首页…</div>' } },
    { path: '/login', component: LoginPage },
    { path: '/projects', redirect: '/long' },
    { path: '/appearance', redirect: '/theme' },
    { path: '/long', component: ProjectsPage, props: { form: 'long' } },
    { path: '/short', component: ProjectsPage, props: { form: 'short' } },
    { path: '/long/new', component: NewProjectPage, props: { form: 'long' } },
    { path: '/short/new', component: ShortCreationPage },
    { path: '/projects/new', component: NewProjectPage },
    { path: '/account', component: AccountPage },
    { path: '/environment', component: EnvironmentPage },
    { path: '/theme', component: AppearancePage },
    { path: '/styles', component: StyleLibraryPage },
    { path: '/writing-resources', component: WritingResourceLibraryPage },
    { path: '/projects/:projectId', component: WorkspacePage },
    { path: '/projects/:projectId/settings', component: SettingsPage },
    { path: '/projects/:projectId/resources', component: ResourcesPage },
    { path: '/projects/:projectId/audit', component: AuditPage },
    { path: '/projects/:projectId/lore', component: LorePage },
    { path: '/admin', component: AdminPage, children: [
      { path: '', component: AdminConsole },
      { path: 'pi', component: PiConsolePage },
      { path: 'configuration', redirect: '/admin/models' },
      { path: 'models', component: PlatformConfiguration, props: { section: 'models' } },
      { path: 'model-routes', component: PlatformConfiguration, props: { section: 'routes' } },
      { path: 'defaults', component: PlatformConfiguration, props: { section: 'defaults' } },
      { path: 'prompts', component: WritingResources, props: { scope: 'prompts' } },
      { path: 'genres', component: WritingResources, props: { scope: 'genres' } },
      { path: 'writing-resources', component: WritingResources },
      { path: 'projects/:projectId', component: ProjectDetailPage },
      { path: 'projects/:projectId/chapters/:chapterId', component: ChapterDetailPage },
      { path: 'tasks/:taskId', component: TaskDetailPage },
      { path: 'runs/:runId', component: RunDetailPage },
      { path: 'users/:userId', component: UserDetailPage },
    ] },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ] })
}
