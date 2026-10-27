<script setup lang="ts">
import { computed, onMounted, onScopeDispose, provide, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import ProjectRail from './components/ProjectRail.vue'
import AdminRail from './components/AdminRail.vue'
import { persistentRailKey } from './navigationContext'
import { subscribeProjectLists } from '../../src/lib/projectListUpdates'
import type { Project } from '../../src/types'
import { authKey } from './authContext'
import { createSessionScope } from './session'
import GuestShell from './components/GuestShell.vue'
import CanvasMedia from './components/CanvasMedia.vue'
import FeedbackWidget from './components/FeedbackWidget.vue'
import AppVersionGuard from './components/AppVersionGuard.vue'
import RouteBoundary from './components/RouteBoundary.vue'
import { createThemeScope, themeKey } from './themeContext'

const theme = createThemeScope()
provide(themeKey, theme)
const { video } = theme
const auth = createSessionScope()
provide(authKey, auth)
const route = useRoute()
const router = useRouter()
const { session, status, error, notice } = auth
provide(persistentRailKey, true)
const navigationProjects = ref<Project[]>([])
watch(() => status.value === 'authenticated' ? session.value?.userId : null, (identity, _, onCleanup) => {
  navigationProjects.value = []
  if (identity) onCleanup(subscribeProjectLists(projects => { navigationProjects.value = projects }))
}, { immediate: true, flush: 'sync' })
const showAdminRail = computed(() => route.path.startsWith('/admin') || (route.path === '/account' && session.value?.role === 'admin' && session.value.roleVerified))
const showProjectRail = computed(() => route.path !== '/login' && !showAdminRail.value)
watch([() => route.path, status, session], () => {
  if (route.path === '/' && (status.value === 'anonymous' || (status.value === 'authenticated' && session.value?.roleVerified))) {
    void router.replace(session.value?.role === 'admin' ? '/admin' : '/long')
  }
}, { immediate: true })
const projectRoute = computed(() => /^\/projects\/[^/]+/.test(route.path) && route.path !== '/projects/new')
onMounted(() => { void auth.start(); void theme.start() })
onScopeDispose(theme.dispose)
onScopeDispose(auth.dispose)
</script>

<template>
  <div class="candidate-app">
    <CanvasMedia v-if="video" v-bind="video" />
    <AppVersionGuard />
    <ProjectRail v-if="status === 'authenticated' || status === 'anonymous'" :key="session?.userId ?? 'guest'" :visible="showProjectRail" :projects="navigationProjects" persistent />
    <AdminRail v-if="status === 'authenticated' || status === 'anonymous'" :key="session?.userId ?? 'guest'" :visible="showAdminRail" persistent />
    <RouteBoundary v-if="route.path === '/login'"><RouterView /></RouteBoundary>
    <div v-else-if="status === 'checking'" class="empty">正在验证登录状态…</div>
    <div v-else-if="status === 'unavailable'" class="empty" role="alert">
      <p>{{ error }}</p><button type="button" class="btn btn-primary" @click="auth.revalidate">重试</button>
      <button type="button" class="btn btn-secondary" @click="auth.logout">退出登录</button>
    </div>
    <GuestShell v-else-if="status === 'anonymous'">
      <div v-if="projectRoute" class="empty" data-guest-exempt><p>未登录，无法打开作品。</p><RouterLink to="/login" class="btn btn-primary">登录</RouterLink></div>
      <RouteBoundary v-else><RouterView v-slot="{ Component }"><component :is="Component" username="未登录" :guest="true" /></RouterView></RouteBoundary>
      <p v-if="notice" role="status">{{ notice }}</p>
    </GuestShell>
    <template v-else-if="session">
      <FeedbackWidget :key="session.userId" />
      <div v-if="error" role="alert" class="banner banner-error">{{ error }}</div>
      <RouteBoundary>
<RouterView v-slot="{ Component }">
        <KeepAlive :key="`${session.userId}:${session.role}`" include="ShortCreationPage" :max="1">
          <component :is="Component" :key="session.userId" :username="session.username" @logout="auth.logout" />
        </KeepAlive>
      </RouterView>
</RouteBoundary>
    </template>
  </div>
</template>

<style>
.candidate-app { height: 100%; display: flex; flex-direction: column; }
.candidate-app > .banner { flex-shrink: 0; margin: 0; }
.candidate-app > :last-child { flex: 1; min-height: 0; }
</style>
