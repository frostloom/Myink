<script setup lang="ts">
import { computed, nextTick, onUnmounted, provide, ref, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import AdminRail from '../components/AdminRail.vue'
import { useAuth } from '../authContext'
import { adminContextKey } from './admin/context'
import styles from '../../../src/pages/AdminPage.module.css'
const { session, status, revalidate, logout } = useAuth()
const route = useRoute()
const router = useRouter()
let traversingHistory = false
const stopHistoryListener = router.options.history.listen(() => { traversingHistory = true })
const main = ref<HTMLElement | null>(null)
const content = ref<HTMLElement | null>(null)
const scrollPositions = new Map<string, number>()
let restoreObserver: ResizeObserver | undefined
watch(() => route.fullPath, async (next, previous) => {
  restoreObserver?.disconnect()
  scrollPositions.set(previous, main.value?.scrollTop ?? 0)
  const shouldRestore = traversingHistory || router.options.history.state.adminRestoreScroll === true
  traversingHistory = false
  await nextTick()
  if (route.fullPath !== next || !main.value) return
  const target = shouldRestore ? scrollPositions.get(next) ?? 0 : 0
  const restore = () => {
    if (!main.value) return
    main.value.scrollTop = target
    if (main.value.scrollTop >= target) restoreObserver?.disconnect()
  }
  restore()
  // The returning list can still be loading; restore once its rows occupy space.
  if (target > (main.value.scrollTop || 0) && content.value && typeof ResizeObserver !== 'undefined') {
    restoreObserver = new ResizeObserver(restore)
    restoreObserver.observe(content.value)
  }
})
onUnmounted(() => { restoreObserver?.disconnect(); stopHistoryListener() })
const stopRestoring = () => restoreObserver?.disconnect()
const forbidden = ref(false)
const identity = computed(() => session.value?.userId ?? '')
watch(identity, () => { forbidden.value = false })
function onForbidden() { forbidden.value = true; void revalidate() }
provide(adminContextKey, { get token() { return session.value?.token ?? '' }, onForbidden })
const allowed = computed(() => status.value === 'authenticated' && session.value?.role === 'admin' && session.value.roleVerified === true)
</script>
<template>
  <div v-if="forbidden" :class="styles.denied" role="alert"><h1>管理员权限已变化</h1><p>受保护数据已清除，正在重新验证当前会话。</p></div>
  <div v-else ref="main" :class="styles.wrap" @wheel.passive="stopRestoring" @touchstart.passive="stopRestoring" @keydown="stopRestoring">
    <AdminRail :on-logout="logout" />
    <main ref="content" :class="styles.main">
      <RouterView v-if="allowed" :key="`${identity}:${route.path}`" />
      <div v-else class="empty">只有管理员可以打开控制台。</div>
    </main>
  </div>
</template>
